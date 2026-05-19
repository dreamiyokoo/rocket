import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers.analysis import router as analysis_router
from routers.auth import router as auth_router
from routers.evals import router as evals_router
from routers.rounds import router as rounds_router
from routers.ws import router as ws_router

app = FastAPI(title="Rocket API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(rounds_router)
app.include_router(analysis_router)
app.include_router(evals_router)
app.include_router(ws_router)


@app.get("/api/v1/health")
async def health():
    return {"status": "ok"}
