import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import admin, board, choices, collaborators, health, intake, me, places, plans, share, transit, trips

logging.basicConfig(level=logging.INFO)
settings = get_settings()

app = FastAPI(title="Trip Planner API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(me.router)
app.include_router(trips.router)
app.include_router(intake.router)
app.include_router(board.router)
app.include_router(choices.router)
app.include_router(share.router)
app.include_router(plans.router)
app.include_router(places.router)
app.include_router(transit.router)
app.include_router(collaborators.router)
app.include_router(admin.router)
