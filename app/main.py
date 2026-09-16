from fastapi import FastAPI

app = FastAPI(title="Industrial Equipment Monitoring Backend")


@app.get("/health")
def health():
    return {"status": "ok"}
