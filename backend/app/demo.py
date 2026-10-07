"""Seed synthetic match events for local development without Riot credentials."""
from getpass import getpass

from sqlalchemy import text

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.security import password_hasher
from app.schemas.auth import Register


def main() -> None:
    if settings.app_env != "development":
        raise RuntimeError("Synthetic demo data is only allowed in development")
    data = Register(email=input("Demo account email: "), password=getpass("Password (12+ characters): "), display_name="Demo player")
    with SessionLocal() as db:
        if db.scalar(text("SELECT id FROM users WHERE lower(email)=:email"), {"email": data.email}):
            raise RuntimeError("Choose a new email; existing accounts are not modified")
        uid = db.scalar(text("INSERT INTO users(email,password_hash,display_name) VALUES (:email,:hash,:name) RETURNING id"),
            {"email": data.email, "hash": password_hasher.hash(data.password), "name": data.display_name})
        match = db.scalar(text("INSERT INTO matches(riot_match_id,map_id,queue_id,started_at,duration_ms) "
            "VALUES (:riot_id,'synthetic','DEMO: synthetic timestamps',now(),30000) RETURNING id"), {"riot_id": f"demo-{uid}"})
        puuid = f"synthetic-{uid}"
        db.execute(text("INSERT INTO match_players(match_id,puuid,user_id) VALUES (:match,:puuid,:uid)"),
            {"match": match, "puuid": puuid, "uid": uid})
        db.execute(text("INSERT INTO rounds(match_id,round_number) VALUES (:match,0)"), {"match": match})
        for time in [5000, 15000, 25000]:
            db.execute(text("INSERT INTO kill_events(match_id,round_number,killer_puuid,victim_puuid,time_since_game_start_ms,time_since_round_start_ms) "
                "VALUES (:match,0,:puuid,'synthetic-opponent',CAST(:time AS INTEGER),CAST(:time AS INTEGER))"),
                {"match": match, "puuid": puuid, "time": time})
        db.commit()
    print("Synthetic demo match created. Sign in and upload a recording of at least 30 seconds.")


if __name__ == "__main__":
    main()
