# MemoryProvider big-file benchmark, run by hand:
#   .venv/bin/python tests/by_hand/bench_memory_big_file.py [--size-mb 1024] [--quick]
# Spawns a real server subprocess (memory provider only), then measures
# PUT/GET throughput, metadata latency, Range GET, and the server RSS
# timeline (baseline / upload peak / after GET / after DELETE).

import argparse
import base64
import http.client
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

USERNAME = "username"
PASSWORD = "password"
CHUNK_SIZE = 4 * 1024 * 1024

CONFIG_TEMPLATE = """\
[[account_mapping]]
username = "{username}"
password = "{password}"
permissions = ["+"]
admin = true

[[provider_mapping]]
prefix = "/"
uri = "memory:///"
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size-mb", type=int, default=1024)
    parser.add_argument("--quick", action="store_true", help="run with 256MB")
    return parser.parse_args()


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def read_rss_mb(pid: int) -> float:
    output = subprocess.run(
        ["ps", "-o", "rss=", "-p", str(pid)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return float(output) / 1024


class RSSSampler:
    """Sample the child process RSS in the background, tracking the max."""

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.max_rss_mb = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _sample_loop(self) -> None:
        while not self._stop.is_set():
            rss = read_rss_mb(self.pid)
            if rss > self.max_rss_mb:
                self.max_rss_mb = rss
            time.sleep(0.1)

    def __enter__(self) -> "RSSSampler":
        self.max_rss_mb = read_rss_mb(self.pid)
        self._thread = threading.Thread(target=self._sample_loop)
        self._thread.start()
        return self

    def __exit__(self, *args: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()


def auth_header() -> str:
    token = base64.b64encode(f"{USERNAME}:{PASSWORD}".encode()).decode()
    return f"Basic {token}"


def request_small(
    port: int,
    method: str,
    path: str,
    body: bytes | None = None,
    extra_headers: dict[str, str] | None = None,
) -> tuple[int, bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=300)
    headers = {"Authorization": auth_header()}
    if extra_headers:
        headers |= extra_headers
    conn.request(method, path, body=body, headers=headers)
    response = conn.getresponse()
    payload = response.read()
    status = response.status
    conn.close()
    return status, payload


def streaming_put(
    port: int, path: str, chunk: bytes, total_bytes: int
) -> tuple[int, float]:
    """PUT total_bytes built from repeated chunks; returns (status, seconds)."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=600)
    conn.putrequest("PUT", path)
    conn.putheader("Authorization", auth_header())
    conn.putheader("Content-Length", str(total_bytes))
    conn.endheaders()

    start = time.perf_counter()
    sent = 0
    while sent < total_bytes:
        n = min(len(chunk), total_bytes - sent)
        conn.send(chunk[:n])
        sent += n

    response = conn.getresponse()
    response.read()
    seconds = time.perf_counter() - start
    status = response.status
    conn.close()
    return status, seconds


def streaming_get(port: int, path: str) -> tuple[int, int, float]:
    """GET and drain the body; returns (status, received_bytes, seconds)."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=600)
    conn.request("GET", path, headers={"Authorization": auth_header()})

    start = time.perf_counter()
    response = conn.getresponse()
    total = 0
    while True:
        block = response.read(CHUNK_SIZE)
        if not block:
            break
        total += len(block)
    seconds = time.perf_counter() - start
    status = response.status
    conn.close()
    return status, total, seconds


def print_row(label: str, value: str) -> None:
    print(f"{label:52s} {value}")


def main() -> None:
    args = parse_args()
    size_bytes = (256 if args.quick else args.size_mb) * 1024 * 1024
    size_mb = size_bytes / 1024 / 1024

    port = free_port()
    with tempfile.TemporaryDirectory() as tmp_dir:
        config_path = Path(tmp_dir) / "bench.toml"
        config_path.write_text(
            CONFIG_TEMPLATE.format(username=USERNAME, password=PASSWORD)
        )

        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "asgi_webdav",
                "-c",
                str(config_path),
                "-P",
                str(port),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        try:
            # wait for the server to accept connections
            for _ in range(100):
                try:
                    request_small(port, "OPTIONS", "/")
                    break
                except OSError:
                    time.sleep(0.1)
            else:
                message = "server did not become ready"
                raise RuntimeError(message)

            rss_baseline = read_rss_mb(process.pid)
            chunk = os.urandom(CHUNK_SIZE)
            path = "/bench-big-file.bin"

            print(f"MemoryProvider big-file benchmark: {size_mb:.0f}MB")
            print_row("RSS baseline (MB)", f"{rss_baseline:.0f}")

            # PUT new file
            with RSSSampler(process.pid) as sampler:
                status, seconds = streaming_put(port, path, chunk, size_bytes)
            assert status == 201, status
            print_row(
                f"PUT {size_mb:.0f}MB",
                f"{status} {seconds:.2f}s {size_mb / seconds:.0f} MB/s",
            )
            print_row("RSS peak during upload (MB)", f"{sampler.max_rss_mb:.0f}")
            rss_after_put = read_rss_mb(process.pid)
            print_row("RSS after upload (MB)", f"{rss_after_put:.0f}")

            # metadata operations
            start = time.perf_counter()
            status, _ = request_small(port, "HEAD", path)
            head_seconds = time.perf_counter() - start
            assert status == 200, status

            propfind_body = (
                b'<?xml version="1.0"?><D:propfind xmlns:D="DAV:">'
                b"<D:prop><D:getcontentlength/></D:prop></D:propfind>"
            )
            start = time.perf_counter()
            status, _ = request_small(port, "PROPFIND", path, body=propfind_body)
            propfind_seconds = time.perf_counter() - start
            assert status == 207, status
            print_row(
                "HEAD / PROPFIND latency (ms)",
                f"{head_seconds * 1e3:.1f} / {propfind_seconds * 1e3:.1f}",
            )

            # GET full body
            status, received, seconds = streaming_get(port, path)
            assert status == 200, status
            assert received == size_bytes, received
            print_row(
                f"GET {size_mb:.0f}MB",
                f"{status} {seconds:.2f}s {size_mb / seconds:.0f} MB/s",
            )
            rss_after_get = read_rss_mb(process.pid)
            print_row("RSS after GET (MB)", f"{rss_after_get:.0f}")

            # Range GET (first 4MB)
            start = time.perf_counter()
            status, payload = request_small(
                port,
                "GET",
                path,
                extra_headers={"Range": f"bytes=0-{CHUNK_SIZE - 1}"},
            )
            range_seconds = time.perf_counter() - start
            assert status == 206, status
            assert len(payload) == CHUNK_SIZE
            print_row("Range GET 4MB (ms)", f"{range_seconds * 1e3:.1f}")

            # overwrite (old and new content coexist briefly)
            with RSSSampler(process.pid) as sampler:
                status, seconds = streaming_put(port, path, chunk, size_bytes)
            assert status == 201, status
            print_row(
                f"PUT overwrite {size_mb:.0f}MB",
                f"{status} {seconds:.2f}s {size_mb / seconds:.0f} MB/s",
            )
            print_row("RSS peak during overwrite (MB)", f"{sampler.max_rss_mb:.0f}")

            # DELETE, then check the RSS falls back
            status, _ = request_small(port, "DELETE", path)
            assert status == 204, status
            time.sleep(1)
            rss_after_delete = read_rss_mb(process.pid)
            print_row("RSS after DELETE (MB)", f"{rss_after_delete:.0f}")

        finally:
            process.terminate()
            process.wait(timeout=10)


if __name__ == "__main__":
    main()
