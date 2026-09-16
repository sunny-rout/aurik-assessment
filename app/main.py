from fastapi import FastAPI

from app.api.ingest import router as ingest_router

app = FastAPI(title="Industrial Equipment Monitoring Backend")

app.include_router(ingest_router)


@app.get("/health")
def health():
    return {"status": "ok"}
