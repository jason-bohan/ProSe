"""Local WebSocket "glasses" receiver -- a stand-in for physical smart-glasses
hardware (Vuzix / HoloLens / Brilliant Labs) so ``prose.device.WebSocketTransport``
can be driven over a real socket in tests without an SDK or emulator download.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time

import websockets


class GlassesEmulator:
    """Accepts WebSocket connections and records every JSON HUD frame received,
    the way a real headset's companion app would consume the BLE/WS bridge."""

    def __init__(self) -> None:
        self._received: list[dict] = []
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server = None
        self._port: int | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()

    @property
    def url(self) -> str:
        assert self._port is not None, "emulator not started"
        return f"ws://127.0.0.1:{self._port}"

    @property
    def received(self) -> list[dict]:
        with self._lock:
            return list(self._received)

    def wait_for_count(self, count: int, timeout: float = 2.0) -> list[dict]:
        """Poll until at least ``count`` frames have been received.

        The client's send()/close() returning only means the bytes hit the
        socket, not that this handler's coroutine (running on its own
        thread/loop) has processed them yet -- callers must synchronize on
        the actual receipt, not on the client call returning.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            current = self.received
            if len(current) >= count:
                return current
            time.sleep(0.01)
        return self.received

    async def _handler(self, websocket, *_args: object) -> None:
        async for message in websocket:
            with self._lock:
                self._received.append(json.loads(message))

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        server = loop.run_until_complete(websockets.serve(self._handler, "127.0.0.1", 0))
        self._server = server
        self._port = server.sockets[0].getsockname()[1]
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            loop.run_until_complete(server.wait_closed())
            loop.close()

    def __enter__(self) -> GlassesEmulator:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)
        return self

    def __exit__(self, *exc_info: object) -> None:
        assert self._loop is not None and self._server is not None
        self._loop.call_soon_threadsafe(self._server.close)
        self._loop.call_soon_threadsafe(self._loop.stop)
        assert self._thread is not None
        self._thread.join(timeout=5)
