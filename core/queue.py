"""Manage users waiting for human servicers."""

import time

from .models import QueueEntry


class QueueManager:
    def __init__(self, servicer_ids: list[str], queue_timeout: int):
        self.queue_timeout = queue_timeout
        self.servicer_queue: dict[str, list[QueueEntry]] = {
            servicer_id: [] for servicer_id in servicer_ids
        }

    def add(
        self, servicer_id: str, user_id: str, user_name: str, group_id: str
    ) -> bool:
        queue = self.servicer_queue.setdefault(servicer_id, [])
        if any(entry.user_id == user_id for entry in queue):
            return False
        queue.append(QueueEntry(user_id, user_name, group_id))
        return True

    def get_position(self, servicer_id: str, user_id: str) -> int:
        for index, entry in enumerate(self.servicer_queue.get(servicer_id, []), 1):
            if entry.user_id == user_id:
                return index
        return -1

    def remove(self, user_id: str) -> bool:
        removed = False
        for servicer_id, queue in self.servicer_queue.items():
            remaining = [entry for entry in queue if entry.user_id != user_id]
            if len(remaining) != len(queue):
                removed = True
                self.servicer_queue[servicer_id] = remaining
        return removed

    def get_size(self, servicer_id: str) -> int:
        return len(self.servicer_queue.get(servicer_id, []))

    def pop_next(self, servicer_id: str) -> QueueEntry | None:
        queue = self.servicer_queue.get(servicer_id, [])
        return queue.pop(0) if queue else None

    def pop_expired(self) -> list[QueueEntry]:
        if self.queue_timeout <= 0:
            return []

        now = time.monotonic()
        expired = []
        for servicer_id, queue in self.servicer_queue.items():
            active = []
            for entry in queue:
                if now - entry.queued_at >= self.queue_timeout:
                    expired.append(entry)
                else:
                    active.append(entry)
            self.servicer_queue[servicer_id] = active
        return expired
