from fastapi import FastAPI

from app.api import auth, boqs, contracts, documents, drawings, office, projects
from app.api.routes import router


app = FastAPI(title="PAACC Construction AI", version="0.2.0")
for r in (router, auth.router, projects.router, contracts.router, documents.router, office.router, drawings.router, boqs.router):
    app.include_router(r, prefix="/api/v1")
