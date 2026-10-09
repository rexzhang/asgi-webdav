import asyncio
from dataclasses import dataclass

import pytest

from asgi_webdav.config import Config
from asgi_webdav.constants import DAVResponseBodyGenerator
from asgi_webdav.request import DAVRequest
from asgi_webdav.response import (
    DAVResponse,
    DAVSenderRaw,
    _watch_client_disconnect,
)

from .kits.asgi import ASGIFakeReceive, ASGIFakeSend, create_asgiref_http_scope_object

CHUNKS = 1000
CHUNK = b"x" * 1024


@dataclass
class StreamProbe:
    """Track how a test body generator was consumed."""

    yielded_chunks: int = 0
    yielded_bytes: int = 0
    closed: bool = False
    exhausted: bool = False


async def _stream(
    probe: StreamProbe,
    chunks: int = CHUNKS,
    chunk: bytes = CHUNK,
    fail_at: int | None = None,
) -> DAVResponseBodyGenerator:
    try:
        for index in range(chunks):
            # scheduling point: lets the watcher task win the race
            await asyncio.sleep(0)
            if fail_at is not None and probe.yielded_chunks == fail_at:
                raise RuntimeError("send error")
            probe.yielded_chunks += 1
            probe.yielded_bytes += len(chunk)
            yield chunk, index < chunks - 1
        probe.exhausted = True
    finally:
        probe.closed = True


def _make_request(fake_receive: ASGIFakeReceive, fake_send: ASGIFakeSend) -> DAVRequest:
    return DAVRequest(
        scope=create_asgiref_http_scope_object(),
        receive=fake_receive,
        send=fake_send,
    )


def _assert_no_leaked_tasks() -> None:
    current = asyncio.current_task()
    remaining = [t for t in asyncio.all_tasks() if t is not current]
    assert remaining == []


class ScriptedReceive:
    def __init__(self, events: list):
        self.events = events
        self.index = 0

    async def __call__(self):
        event = self.events[self.index]
        self.index += 1
        return event


async def test_watch_client_disconnect_skips_http_request_events():
    scripted_receive = ScriptedReceive(
        [
            {"type": "http.request", "body": b"", "more_body": False},
            {"type": "http.request", "body": b"x", "more_body": False},
            {"type": "http.disconnect"},
        ]
    )

    await asyncio.wait_for(_watch_client_disconnect(scripted_receive), timeout=1)
    assert scripted_receive.index == 3


async def test_sender_send_bytes_content_without_watcher():
    fake_receive = ASGIFakeReceive()
    fake_send = ASGIFakeSend()
    request = _make_request(fake_receive, fake_send)

    response = DAVResponse(status=200, content=b"hello")
    sender = DAVSenderRaw(Config(), response)

    await asyncio.wait_for(sender.send(request), timeout=5)

    # bytes content takes the fast path: receive() was never touched
    assert fake_receive.call_count == 0
    assert fake_send.bodys == [b"hello"]
    assert fake_send.status == 200


async def test_sender_send_streaming_completes_normally():
    probe = StreamProbe()
    fake_receive = ASGIFakeReceive()
    fake_send = ASGIFakeSend()
    request = _make_request(fake_receive, fake_send)

    response = DAVResponse(status=200, content=_stream(probe))
    sender = DAVSenderRaw(Config(), response)

    await asyncio.wait_for(sender.send(request), timeout=5)

    assert probe.exhausted is True
    assert probe.closed is True
    assert probe.yielded_chunks == CHUNKS
    assert fake_send.body_calls == CHUNKS
    assert fake_send.body_content_length == CHUNKS * len(CHUNK)
    # the watcher consumed the leftover http.request event and is now
    # blocked in its second receive() call until cancelled
    assert fake_receive.call_count == 2
    _assert_no_leaked_tasks()


async def test_sender_send_aborts_on_client_disconnect():
    probe = StreamProbe()
    fake_receive = ASGIFakeReceive()
    fake_send = ASGIFakeSend()
    request = _make_request(fake_receive, fake_send)

    response = DAVResponse(status=200, content=_stream(probe))
    sender = DAVSenderRaw(Config(), response)

    # arm the disconnect: fire when the 3rd body chunk has been sent
    def trigger_disconnect() -> None:
        if fake_send.body_calls >= 3:
            fake_receive.trigger_disconnect()

    fake_send.on_body = trigger_disconnect

    await asyncio.wait_for(sender.send(request), timeout=5)

    assert probe.yielded_chunks < 50
    assert probe.closed is True
    assert probe.exhausted is False
    assert fake_receive.call_count >= 2
    _assert_no_leaked_tasks()


async def test_sender_send_error_propagates_and_closes_generator():
    probe = StreamProbe()
    fake_receive = ASGIFakeReceive()
    fake_send = ASGIFakeSend()
    request = _make_request(fake_receive, fake_send)

    response = DAVResponse(status=200, content=_stream(probe, fail_at=5))
    sender = DAVSenderRaw(Config(), response)

    with pytest.raises(RuntimeError):
        await asyncio.wait_for(sender.send(request), timeout=5)

    assert probe.closed is True
    assert probe.yielded_chunks == 5
    _assert_no_leaked_tasks()
