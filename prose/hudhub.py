"""Fan-out hub for live HUD frames shared by the web app, phone, and glasses."""
from __future__ import annotations

import queue
import threading


class HudHub:
    """Publish glass-ready frame payloads to every live SSE subscriber.

    New subscribers immediately receive the current frame, so a late-joining
    bridge (or page reload) shows the present state instead of going blank.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: list[queue.Queue[dict]] = []
        self._current: dict | None = None
        self._seq = 0

    def publish(self, payload: dict) -> dict:
        with self._lock:
            self._seq += 1
            frame = {**payload, "seq": self._seq}
            self._current = frame
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            try:
                subscriber.put_nowait(frame)
            except queue.Full:
                continue  # A stalled reader resyncs from the current frame.
        return frame

    @property
    def current(self) -> dict | None:
        with self._lock:
            return dict(self._current) if self._current is not None else None

    @property
    def seq(self) -> int:
        with self._lock:
            return self._seq

    def subscribe(self) -> queue.Queue:
        subscriber: queue.Queue = queue.Queue(maxsize=8)
        with self._lock:
            if self._current is not None:
                subscriber.put_nowait(dict(self._current))
            self._subscribers.append(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: queue.Queue) -> None:
        with self._lock:
            if subscriber in self._subscribers:
                self._subscribers.remove(subscriber)
