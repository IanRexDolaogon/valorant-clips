from datetime import datetime, timezone

from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.services import riot_client


class Info(BaseModel):
    matchId: str = Field(min_length=1, max_length=100)
    mapId: str = Field(min_length=1, max_length=100)
    gameStartMillis: int = Field(ge=0, le=253402300799000)
    gameLengthMillis: int = Field(gt=0, le=2147483647)
    queueId: str | None = Field(default=None, max_length=50)


class Player(BaseModel):
    puuid: str = Field(min_length=1, max_length=100)
    characterId: str | None = Field(default=None, max_length=100)
    teamId: str | None = Field(default=None, max_length=20)


class Kill(BaseModel):
    killer: str = Field(min_length=1, max_length=100)
    victim: str = Field(min_length=1, max_length=100)
    timeSinceGameStartMillis: int = Field(ge=0, le=2147483647)
    timeSinceRoundStartMillis: int = Field(ge=0, le=2147483647)


class Stats(BaseModel):
    kills: list[Kill] = Field(default_factory=list, max_length=1000)


class Round(BaseModel):
    roundNum: int = Field(ge=0, le=32767)
    winningTeam: str | None = Field(default=None, max_length=20)
    playerStats: list[Stats] = Field(default_factory=list, max_length=20)


class Match(BaseModel):
    matchInfo: Info
    players: list[Player] = Field(min_length=1, max_length=20)
    roundResults: list[Round] = Field(max_length=100)


def owned_match(db: Session, user_id: int, match_id: int) -> None:
    if not db.scalar(text("SELECT match_id FROM match_players WHERE match_id=:id AND user_id=:uid"),
        {"id": match_id, "uid": user_id}):
        raise HTTPException(404, "Match not found")


def ingest(db: Session, user_id: int, account_id: int, riot_match_id: str) -> int:
    account = db.execute(text("SELECT puuid,region FROM riot_accounts WHERE id=:id AND user_id=:uid"),
        {"id": account_id, "uid": user_id}).mappings().first()
    if not account:
        raise HTTPException(404, "Riot account not found")
    existing = db.scalar(text("SELECT id FROM matches WHERE riot_match_id=:id"), {"id": riot_match_id})
    if existing:
        player = db.scalar(text("SELECT puuid FROM match_players WHERE match_id=:id AND puuid=:puuid"),
            {"id": existing, "puuid": account["puuid"]})
        if not player:
            raise HTTPException(403, "Your linked account is not in this match")
        db.execute(text("UPDATE match_players SET user_id=:uid WHERE match_id=:id AND puuid=:puuid"),
            {"uid": user_id, "id": existing, "puuid": player})
        db.commit()
        return existing
    try:
        match = Match.model_validate(riot_client.fetch_match(account["region"], riot_match_id))
    except ValidationError:
        raise HTTPException(502, "Invalid Riot match data") from None
    if match.matchInfo.matchId != riot_match_id:
        raise HTTPException(502, "Riot returned a different match")
    if account["puuid"] not in {p.puuid for p in match.players}:
        raise HTTPException(403, "Your linked account is not in this match")
    try:
        info = match.matchInfo
        match_id = db.scalar(text(
            "INSERT INTO matches(riot_match_id,map_id,queue_id,started_at,duration_ms) "
            "VALUES (:riot_id,:map,:queue,:start,:duration) RETURNING id"),
            {"riot_id": info.matchId, "map": info.mapId, "queue": info.queueId,
             "start": datetime.fromtimestamp(info.gameStartMillis / 1000, timezone.utc), "duration": info.gameLengthMillis})
        for player in match.players:
            db.execute(text("INSERT INTO match_players(match_id,puuid,user_id,agent_id,team_id) "
                "VALUES (:id,CAST(:puuid AS VARCHAR(100)),(SELECT user_id FROM riot_accounts WHERE puuid=:puuid),:agent,:team)"),
                {"id": match_id, "puuid": player.puuid, "agent": player.characterId, "team": player.teamId})
        for round in match.roundResults:
            db.execute(text("INSERT INTO rounds(match_id,round_number,winning_team) VALUES (:id,:round,:winner)"),
                {"id": match_id, "round": round.roundNum, "winner": round.winningTeam})
            for stats in round.playerStats:
                for kill in stats.kills:
                    db.execute(text("INSERT INTO kill_events(match_id,round_number,killer_puuid,victim_puuid,"
                        "time_since_game_start_ms,time_since_round_start_ms) VALUES (:id,:round,:killer,:victim,:game,:time)"),
                        {"id": match_id, "round": round.roundNum, "killer": kill.killer, "victim": kill.victim,
                         "game": kill.timeSinceGameStartMillis, "time": kill.timeSinceRoundStartMillis})
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Match already imported or Riot match data conflicts; retry") from None
    return match_id
