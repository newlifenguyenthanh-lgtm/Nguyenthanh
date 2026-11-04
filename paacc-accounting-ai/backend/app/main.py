from fastapi import FastAPI

from app.api import auth, contracts, documents, office, projects
from app.api.routes import router


app = FastAPI(title="PAACC Construction AI", version="0.2.0")
for r in (router, auth.router, projects.router, contracts.router, documents.router, office.router):
    app.include_router(r, prefix="/api/v1")
