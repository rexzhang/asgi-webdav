import asyncio
from collections.abc import Callable, Iterable

from asgiref.typing import ASGIReceiveEvent, ASGISendEvent


class ASGIFakeSend:
    status: int
    headers: Iterable[tuple[bytes, bytes]]
    trailers: bool

    bodys: list[bytes]
    body_content_length: int = 0
    body_calls: int = 0

    def __init__(self, on_body: Callable[[], None] | None = None) -> None:
        self.bodys = list()
        self.on_body = on_body

    async def __call__(self, event: ASGISendEvent) -> None:
        if "status" in event:
            self.status = event["status"]

        if "headers" in event:
            self.headers = event["headers"]

        if "trailers" in event:
            self.trailers = event["trailers"]

        if "body" in event:
            body = event["body"]
            self.bodys.append(body)
            self.body_calls += 1
            self.body_content_length += len(body)
            if self.on_body is not None:
                self.on_body()

    def __repr__(self) -> str:
        return f"FakeASGISend(): {self.status}, {self.headers}, {self.trailers}, body * {len(self.bodys)}, calls * {self.body_calls}"


class ASGIFakeReceive:
    """Fake ASGI receive channel for disconnect tests.

    The first call returns a leftover http.request event; later calls block
    until trigger_disconnect() is called, then return http.disconnect.
    """

    call_count: int = 0

    def __init__(self) -> None:
        self._disconnect_event = asyncio.Event()

    def trigger_disconnect(self) -> None:
        self._disconnect_event.set()

    async def __call__(self) -> ASGIReceiveEvent:
        self.call_count += 1
        if self.call_count == 1:
            return {"type": "http.request", "body": b"", "more_body": False}

        await self._disconnect_event.wait()
        return {"type": "http.disconnect"}
