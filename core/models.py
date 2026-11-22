"""Domain models shared by the human service plugin."""

import time
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime
from enum import Enum
from typing import Any


def _serialize(value: Any) -> Any:
    """Convert nested domain values into JSON-friendly primitives."""
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: _serialize(getattr(value, item.name)) for item in fields(value)
        }
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_serialize(item) for item in value]
    return value


class SessionStatus(str, Enum):
    WAITING = "waiting"
    CONNECTED = "connected"


@dataclass(slots=True)
class ServiceSession:
    user_id: str
    group_id: str
    user_name: str
    servicer_id: str = ""
    servicer_name: str = ""
    status: SessionStatus = SessionStatus.WAITING
    assigned_servicer_id: str | None = None
    last_active_at: float | None = None


@dataclass(slots=True)
class QueueEntry:
    user_id: str
    user_name: str
    group_id: str
    queued_at: float = field(default_factory=time.monotonic)


@dataclass(slots=True, frozen=True)
class ChatRecord:
    sender_id: str
    name: str
    message: str
    timestamp: str

    @classmethod
    def create(cls, sender_id: str, name: str, message: str) -> "ChatRecord":
        return cls(
            sender_id=sender_id,
            name=name,
            message=message,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )


@dataclass(slots=True, frozen=True)
class Notification:
    message: str
    group_id: str | None = None
    user_id: str | None = None


@dataclass(slots=True, frozen=True)
class HistoryExport:
    servicer_id: str
    history: list[ChatRecord]


@dataclass(slots=True)
class ServiceResult:
    code: str
    message: str = ""
    ok: bool = True
    data: dict[str, Any] = field(default_factory=dict)
    notifications: list[Notification] = field(default_factory=list)
    history_exports: list[HistoryExport] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)
