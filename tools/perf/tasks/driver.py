"""Pure-stdlib asynchronous HTTP load driver for ASGI-WebDAV benchmarks.

This module has NO third-party dependencies on purpose: it runs both on the
macOS host (as the fallback load generator when ``oha`` is unavailable) and
inside the lima VM (where Debian ships no ``oha`` package), driven by any
Python >= 3.11.

Run directly::

    python tools/perf/tasks/driver.py --host 127.0.0.1 --port 8000 \\
        --method GET --path /fs/4k.bin --duration 10 -c 4 \\
        --auth username:password --json

or as a module::

    python -m tools.perf.tasks.driver ... --json

Output is a single JSON object on stdout (unless ``--output`` is given).
Metrics: request count, error count, per-status-class counters, RPS and
latency percentiles (p50/p90/p99, milliseconds).
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import sys
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

USER_AGENT = "asgi-webdav-perf-driver/1.0"

DEFAULT_TIMEOUT = 30.0


@dataclass
class DriverTarget:
    host: str
    port: int
    method: str
    path: str
    auth_header: bytes | None = None
    extra_headers: list[tuple[bytes, bytes]] = field(default_factory=list)
    body: bytes | None = None
    timeout: float = DEFAULT_TIMEOUT


@dataclass
class DriverResult:
    method: str
    path: str
    concurrency: int
    mode: str
    requested_duration: float | None
    requested_count: int | None
    duration: float
    requests: int
    errors: int
    status_counts: dict[str, int]
    rps: float
    lat_ms_p50: float
    lat_ms_p90: float
    lat_ms_p99: float
    lat_ms_mean: float
    bytes_read: int

    def to_dict(self) -> dict[str, object]:
        return {
            "loadgen": "driver",
            "method": self.method,
            "path": self.path,
            "concurrency": self.concurrency,
            "mode": self.mode,
            "requested_duration": self.requested_duration,
            "requested_count": self.requested_count,
            "duration": round(self.duration, 3),
            "requests": self.requests,
            "errors": self.errors,
            "status_counts": self.status_counts,
            "rps": round(self.rps, 2),
            "lat_ms_p50": round(self.lat_ms_p50, 3),
            "lat_ms_p90": round(self.lat_ms_p90, 3),
            "lat_ms_p99": round(self.lat_ms_p99, 3),
            "lat_ms_mean": round(self.lat_ms_mean, 3),
            "bytes_read": self.bytes_read,
        }


class _ConnectionClosed(Exception):
    """The peer closed the connection mid-exchange."""


def _build_target(args: argparse.Namespace) -> DriverTarget:
    headers: list[tuple[bytes, bytes]] = [
        (b"user-agent", USER_AGENT.encode("ascii")),
        (b"accept-encoding", b"gzip, deflate"),
    ]
    for raw in args.header or ():
        key, sep, value = raw.partition(":")
        if not sep:
            msg = f"invalid header (expected 'Key: Value'): {raw!r}"
            raise SystemExit(msg)
        headers.append(
            (key.strip().lower().encode("ascii"), value.strip().encode("utf-8"))
        )

    auth_header: bytes | None = None
    if args.auth:
        username, _, password = args.auth.partition(":")
        raw = f"{username}:{password}".encode()
        auth_header = b"Basic " + base64.b64encode(raw)

    body: bytes | None = None
    if args.body_file is not None:
        body = Path(args.body_file).read_bytes()
    elif args.body is not None:
        body = args.body.encode("utf-8")

    return DriverTarget(
        host=args.host,
        port=args.port,
        method=args.method.upper(),
        path=args.path,
        auth_header=auth_header,
        extra_headers=headers,
        body=body,
        timeout=args.timeout,
    )


def _build_request(target: DriverTarget) -> bytes:
    lines = [
        f"{target.method} {target.path} HTTP/1.1",
        f"Host: {target.host}:{target.port}",
        "Connection: keep-alive",
    ]
    for key, value in target.extra_headers:
        lines.append(f"{key.decode('latin-1')}: {value.decode('latin-1')}")
    if target.auth_header is not None:
        lines.append(f"Authorization: {target.auth_header.decode('latin-1')}")
    if target.body is not None:
        lines.append(f"Content-Length: {len(target.body)}")
    head = ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1")
    if target.body is not None:
        return head + target.body
    return head


async def _read_response(
    reader: asyncio.StreamReader, *, no_body: bool
) -> tuple[int, int]:
    """Read one full HTTP response, return (status, body bytes read)."""
    status_line = await reader.readline()
    if not status_line:
        raise _ConnectionClosed
    parts = status_line.split(None, 2)
    if len(parts) < 2 or not parts[1].isdigit():
        msg = f"malformed status line: {status_line!r}"
        raise _ConnectionClosed(msg)
    status = int(parts[1])

    content_length: int | None = None
    chunked = False
    while True:
        line = await reader.readline()
        if line in (b"\r\n", b"\n", b""):
            break
        key, _, value = line.decode("latin-1").partition(":")
        key = key.strip().lower()
        value = value.strip()
        if key == "content-length":
            content_length = int(value)
        elif key == "transfer-encoding" and "chunked" in value.lower():
            chunked = True

    body_bytes = 0
    # HEAD (and 204/304) carry no body even when Content-Length is present
    if no_body or status in (204, 304):
        return status, 0
    if chunked:
        while True:
            size_line = await reader.readline()
            size = int(size_line.split(b";")[0].strip() or b"0", 16)
            if size == 0:
                await reader.readline()  # trailing CRLF after last chunk
                break
            body_bytes += size
            await reader.readexactly(size + 2)  # chunk data + CRLF
    elif content_length is not None and content_length > 0:
        remaining = content_length
        while remaining > 0:
            block = await reader.read(min(65536, remaining))
            if not block:
                raise _ConnectionClosed
            body_bytes += len(block)
            remaining -= len(block)
    elif content_length is None and status >= 200:
        # close-delimited response
        while True:
            block = await reader.read(65536)
            if not block:
                break
            body_bytes += len(block)

    return status, body_bytes


async def _worker(
    target: DriverTarget,
    deadline: float | None,
    remaining: list[int],
    counter: Counter[str],
    latencies: list[float],
    total_bytes: list[int],
) -> None:
    """One worker loop: keep-alive connection, sequential request cycles.

    ``remaining`` is a shared one-element cell decremented before any await,
    which makes check-and-decrement atomic under asyncio's cooperative model.
    """
    no_body = target.method == "HEAD"
    conn: tuple[asyncio.StreamReader, asyncio.StreamWriter] | None = None
    try:
        while True:
            if deadline is not None and time.monotonic() >= deadline:
                break
            if deadline is None:
                if remaining[0] <= 0:
                    break
                remaining[0] -= 1
            try:
                if conn is None or conn[1].is_closing():
                    conn = await asyncio.wait_for(
                        asyncio.open_connection(target.host, target.port),
                        timeout=target.timeout,
                    )
                reader, writer = conn
                start = time.perf_counter()
                writer.write(_build_request(target))
                await writer.drain()
                status, body_bytes = await asyncio.wait_for(
                    _read_response(reader, no_body=no_body), timeout=target.timeout
                )
                elapsed_ms = (time.perf_counter() - start) * 1000.0
            except (OSError, TimeoutError, _ConnectionClosed):
                counter["errors"] += 1
                # force a fresh connection on the next cycle
                if conn is not None:
                    try:
                        conn[1].close()
                    except OSError:
                        pass
                conn = None
                continue
            status_class = f"{status // 100}xx"
            counter[status_class] += 1
            if status >= 400:
                counter["errors"] += 1
            else:
                counter["ok"] += 1
            latencies.append(elapsed_ms)
            total_bytes[0] += body_bytes
    finally:
        if conn is not None:
            try:
                conn[1].close()
            except OSError:
                pass


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    index = min(
        len(sorted_values) - 1, max(0, round(pct / 100.0 * (len(sorted_values) - 1)))
    )
    return sorted_values[index]


async def _run_load(
    target: DriverTarget, concurrency: int, duration: float | None, count: int | None
) -> DriverResult:
    counter: Counter[str] = Counter()
    latencies: list[float] = []
    total_bytes = [0]
    remaining = [count if count is not None else 0]
    deadline = time.monotonic() + duration if duration is not None else None
    start = time.perf_counter()
    await asyncio.gather(
        *(
            _worker(target, deadline, remaining, counter, latencies, total_bytes)
            for _ in range(concurrency)
        )
    )
    elapsed = time.perf_counter() - start
    latencies.sort()
    requests = counter["ok"] + counter["errors"]
    return DriverResult(
        method=target.method,
        path=target.path,
        concurrency=concurrency,
        mode="count" if count is not None else "duration",
        requested_duration=duration,
        requested_count=count,
        duration=elapsed,
        requests=requests,
        errors=counter["errors"],
        status_counts={k: v for k, v in counter.items() if k.endswith("xx")},
        rps=requests / elapsed if elapsed > 0 else 0.0,
        lat_ms_p50=_percentile(latencies, 50),
        lat_ms_p90=_percentile(latencies, 90),
        lat_ms_p99=_percentile(latencies, 99),
        lat_ms_mean=sum(latencies) / len(latencies) if latencies else 0.0,
        bytes_read=total_bytes[0],
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pure-stdlib async HTTP load driver")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--method", default="GET")
    parser.add_argument("--path", default="/")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--duration", type=float, help="run for this many seconds")
    mode.add_argument("--requests", type=int, help="run this many requests (total)")
    parser.add_argument("-c", "--concurrency", type=int, default=1)
    parser.add_argument("--auth", metavar="USER:PASS", help="HTTP Basic auth")
    parser.add_argument("--header", action="append", metavar="KEY: VALUE")
    parser.add_argument("--body", help="request body as text")
    parser.add_argument("--body-file", help="request body read from file")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--output", help="write JSON here instead of stdout")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    target = _build_target(args)
    result = asyncio.run(
        _run_load(target, args.concurrency, args.duration, args.requests)
    )
    payload = json.dumps(result.to_dict(), indent=2)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    else:
        sys.stdout.write(payload + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
