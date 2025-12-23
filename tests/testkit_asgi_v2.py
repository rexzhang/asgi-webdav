from collections.abc import Iterable

from asgiref.typing import ASGISendEvent


class ASGIFakeSend:
    status: int
    headers: Iterable[tuple[bytes, bytes]]
    trailers: bool

    bodys: list[bytes]
    body_content_length: int = 0
    body_calls: int = 0

    def __init__(self) -> None:
        self.bodys = list()

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

    def __repr__(self) -> str:
        return f"FakeASGISend(): {self.status}, {self.headers}, {self.trailers}, body * {len(self.bodys)}, calls * {self.body_calls}"
