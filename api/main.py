from fastapi import FastAPI

app = FastAPI(title="Rocket API")


@app.get("/api/v1/health")
async def health():
    return {"status": "ok"}
