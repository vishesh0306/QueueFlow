from fastapi import FastAPI

app = FastAPI(title="QueueFlow")


@app.get("/health")
def health():
    return {"status": "ok"}
