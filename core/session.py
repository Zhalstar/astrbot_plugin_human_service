"""Manage active human service sessions."""

import time

from .models import (
    ServiceSession,
    SessionStatus,
)


class SessionManager:
    def __init__(self, idle_timeout: int):
        self.idle_timeout = idle_timeout
        self.session_map: dict[str, ServiceSession] = {}

    def create_session(self, session: ServiceSession) -> None:
        self.session_map[session.user_id] = session

    def get_session(self, user_id: str) -> ServiceSession | None:
        return self.session_map.get(user_id)

    def delete_session(self, user_id: str) -> None:
        self.session_map.pop(user_id, None)

    def has_session(self, user_id: str) -> bool:
        return user_id in self.session_map

    def touch(self, user_id: str) -> None:
        if self.idle_timeout <= 0:
            return
        if session := self.session_map.get(user_id):
            session.last_active_at = time.monotonic()

    def get_idle_user_ids(self) -> list[str]:
        if self.idle_timeout <= 0:
            return []
        now = time.monotonic()
        return [
            session.user_id
            for session in self.session_map.values()
            if session.status is SessionStatus.CONNECTED
            and session.last_active_at is not None
            and now - session.last_active_at >= self.idle_timeout
        ]

    def is_servicer_occupied(self, servicer_id: str) -> bool:
        """Count both connected and assigned waiting sessions as occupied."""
        return any(
            (
                session.status is SessionStatus.CONNECTED
                and session.servicer_id == servicer_id
            )
            or (
                session.status is SessionStatus.WAITING
                and session.assigned_servicer_id == servicer_id
            )
            for session in self.session_map.values()
        )

    def get_user_by_servicer(self, servicer_id: str) -> str | None:
        for session in self.session_map.values():
            if (
                session.servicer_id == servicer_id
                and session.status is SessionStatus.CONNECTED
            ):
                return session.user_id
        return None
