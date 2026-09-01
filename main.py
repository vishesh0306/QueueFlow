from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from api.deps import APIError
from api.routes import admin, patient, staff
from ws.gateway import router as ws_router

app = FastAPI(title="QueueFlow")


@app.exception_handler(APIError)
def handle_api_error(request: Request, exc: APIError):
    return JSONResponse(status_code=exc.status_code, content={"error": {"code": exc.code, "message": exc.message}})


app.include_router(patient.router)
app.include_router(staff.router)
app.include_router(admin.router)
app.include_router(ws_router)


@app.get("/health")
def health():
    return {"status": "ok"}


app.mount("/dashboard", StaticFiles(directory="static/dashboard", html=True), name="dashboard")
