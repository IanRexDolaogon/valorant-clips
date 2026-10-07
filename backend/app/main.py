from fastapi import FastAPI

app = FastAPI(title="Valorant Clips API")


@app.get("/health")
def health():
    return {"status": "ok"}