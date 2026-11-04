from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import auth, contracts, projects
from app.api.routes import router
from app.db import get_engine
from app.models import Base


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(get_engine())  # TODO: replace with Alembic migrations
    yield


app = FastAPI(title="PAACC Construction AI", version="0.2.0", lifespan=lifespan)
for r in (router, auth.router, projects.router, contracts.router):
    app.include_router(r, prefix="/api/v1")
