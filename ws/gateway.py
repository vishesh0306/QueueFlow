import uuid
from collections import defaultdict
from typing import Callable

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from core.estimator import estimated_wait_seconds
from core.token_service import position_in_queue
from db.models import Token
from db.session import SessionLocal


class ConnectionManager:
    """Tracks WebSocket connections per clinic and broadcasts queue_updated events.

    Each connection may optionally be tied to a patient's own token_id (passed as a
    query param on connect); those connections get a personalized payload (their
    live position/ETA). Connections with no token_id (staff dashboards, a waiting-room
    board) just get the bare event, enough to know "something changed, re-fetch."
    """

    def __init__(self, session_factory: Callable[[], Session] = SessionLocal):
        self._connections: dict[uuid.UUID, dict[WebSocket, uuid.UUID | None]] = defaultdict(dict)
        self._session_factory = session_factory

    async def connect(self, websocket: WebSocket, clinic_id: uuid.UUID, token_id: uuid.UUID | None) -> None:
        await websocket.accept()
        self._connections[clinic_id][websocket] = token_id

    def disconnect(self, websocket: WebSocket, clinic_id: uuid.UUID) -> None:
        self._connections[clinic_id].pop(websocket, None)

    async def broadcast_queue_updated(self, clinic_id: uuid.UUID, session_id: uuid.UUID) -> None:
        connections = self._connections.get(clinic_id)
        if not connections:
            return

        db = self._session_factory()
        dead: list[WebSocket] = []
        try:
            for websocket, token_id in list(connections.items()):
                payload: dict = {"event": "queue_updated", "session_id": str(session_id)}

                if token_id is not None:
                    token = db.get(Token, token_id)
                    if token is not None:
                        if token.status == "waiting":
                            position = position_in_queue(db, token)
                            eta = estimated_wait_seconds(db, token.session_id, position)
                        else:
                            position = None
                            eta = None
                        payload.update(
                            your_token_id=str(token.id),
                            display_number=token.display_number,
                            status=token.status,
                            position=position,
                            estimated_wait_seconds=eta,
                        )

                try:
                    await websocket.send_json(payload)
                except Exception:
                    dead.append(websocket)
        finally:
            db.close()

        for websocket in dead:
            self.disconnect(websocket, clinic_id)


manager = ConnectionManager()

router = APIRouter()


@router.websocket("/ws/queue/{clinic_id}")
async def queue_ws(websocket: WebSocket, clinic_id: uuid.UUID, token_id: uuid.UUID | None = None):
    await manager.connect(websocket, clinic_id, token_id)
    try:
        while True:
            # No client->server messages are expected; this just keeps the socket
            # open and lets us notice a disconnect.
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, clinic_id)
