from fastapi import FastAPI

from app.api.ingest import router as ingest_router
from app.api.machines import router as machines_router
from app.api.status import router as status_router
from app.api.summary import router as summary_router

app = FastAPI(title="Industrial Equipment Monitoring Backend")

app.include_router(ingest_router)
app.include_router(status_router)
app.include_router(machines_router)
app.include_router(summary_router)


@app.get("/health")
def health():
    return {"status": "ok"}
