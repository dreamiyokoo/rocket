from fastapi import FastAPI

from routers.auth import router as auth_router

app = FastAPI(title="Rocket API")

app.include_router(auth_router)


@app.get("/api/v1/health")
async def health():
    return {"status": "ok"}
