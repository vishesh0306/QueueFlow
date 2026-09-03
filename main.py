import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from api.deps import APIError
from api.routes import admin, patient, staff
from config import settings
from ws.gateway import router as ws_router

# uvicorn configures its own "uvicorn.*" loggers but not the root logger, so a plain
# getLogger(__name__) call here would otherwise go nowhere -- this makes this
# process's own logging (and the in-process worker/telegram_bot threads', which
# reuse the same root handler once it exists) actually show up.
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Free-tier deploy compromise (see config.py) -- runs the notification worker and
    # the Telegram poller as daemon threads in this same process instead of as
    # separate services, for platforms with no free Background Worker type.
    if settings.run_background_workers_in_process:
        import telegram_bot
        import worker as notification_worker

        logger.info("RUN_BACKGROUND_WORKERS_IN_PROCESS is set -- starting worker/telegram_bot as threads")
        threading.Thread(target=notification_worker.main, name="notification-worker", daemon=True).start()
        threading.Thread(target=telegram_bot.main, name="telegram-bot-poller", daemon=True).start()
    yield


app = FastAPI(title="QueueFlow", lifespan=lifespan)


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
app.mount("/patient-app", StaticFiles(directory="static/patient", html=True), name="patient-app")
app.mount("/signup", StaticFiles(directory="static/signup", html=True), name="signup")
# Mounted last, at the root prefix, so it only catches what nothing above already matched.
app.mount("/", StaticFiles(directory="static/home", html=True), name="home")
