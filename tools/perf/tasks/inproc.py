"""In-process ASGI benchmark harness (no network, no uvicorn).

Executed BY the perf CLI as a subprocess under each target interpreter, with
the repo root as cwd so ``tests.kits`` and ``asgi_webdav`` are importable::

    python -m tools.perf.tasks.inproc --requests 1000 --workload all --json

Measures the pure per-request app cost (middleware + auth + dispatch +
provider + response build) using the fake ASGI channels from tests.kits —
this isolates the application from HTTP/uvicorn layers.
"""

from __future__ import annotations

import argparse
import asyncio
import cProfile
import io
import json
import os
import pstats
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    # keep tests.kits importable after the .env-neutralizing chdir below
    sys.path.insert(0, str(_REPO_ROOT))

from tests.kits.asgi import ASGITestClient  # noqa: E402
from tools.perf.config_gen import (  # noqa: E402
    BASIC_PASSWORD,
    BASIC_USERNAME,
    DIGEST_PASSWORD,
    DIGEST_USERNAME,
    build_config_dict,
)

PROPFIND_ALLPROP_BODY = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<D:propfind xmlns:D="DAV:"><D:prop>'
    "<D:displayname/><D:resourcetype/><D:getcontentlength/>"
    "<D:getlastmodified/><D:creationdate/>"
    "</D:prop></D:propfind>"
)
WORKLOADS = ("options", "get-fs", "propfind-mem", "digest")


class BenchClient(ASGITestClient):
    """ASGITestClient whose receive channel ends the disconnect watcher.

    The base fake receive answers every call with another http.request
    event; streaming responses (fs GET) spawn a disconnect watcher that
    would then spin forever. Returning http.disconnect after the request
    body mirrors what a real client does.
    """

    def __init__(self, app: Any) -> None:
        super().__init__(app)
        self._body_sent = False

    async def _fake_receive(self) -> Any:
        if not self._body_sent:
            self._body_sent = True
            return {
                "type": "http.request",
                "body": self.request.data,
                "more_body": False,
            }
        return {"type": "http.disconnect"}

    async def _call_method(self) -> Any:
        self._body_sent = False
        return await super()._call_method()


def _default_fs_dir() -> Path:
    return _REPO_ROOT / "output/perf/fixtures/fs"


def _seed_memory_dir(client: ASGITestClient, entries: int) -> bool:
    """Create /memory/dir-N with entries via MKCOL+PUT; True when seeded."""

    async def seed() -> bool:
        basic = ASGITestClient.create_basic_authorization_headers(
            BASIC_USERNAME, BASIC_PASSWORD
        )
        col = f"/memory/dir-{entries}"
        client.request = _make_request("MKCOL", col, basic, b"")
        response = await client._call_method()
        if response.status_code not in (201, 405):
            return False
        ok = True
        for i in range(entries):
            path = f"{col}/entry-{i:04d}.txt"
            client.request = _make_request("PUT", path, basic, b"x" * 64)
            response = await client._call_method()
            if response.status_code not in (201, 204):
                ok = False
                break
        return ok

    return asyncio.run(seed())


def _make_request(
    method: str, path: str, headers: dict[bytes, bytes], body: bytes
) -> Any:
    # ASGIRequest is a plain dataclass in tests.kits; import here to keep the
    # module-level surface stdlib+project only.
    from tests.kits.asgi import ASGIRequest

    return ASGIRequest(method, path, headers, body)


async def _measure(
    client: ASGITestClient,
    request_factory: Any,
    expected_statuses: set[int],
    requests: int,
    profiler: cProfile.Profile | None,
) -> dict[str, Any]:
    latencies: list[float] = []
    errors = 0
    status_counts: dict[int, int] = {}
    if profiler is not None:
        profiler.enable()
    for _ in range(requests):
        client.request = request_factory()
        start = time.perf_counter()
        response = await client._call_method()
        latencies.append((time.perf_counter() - start) * 1e6)
        status_counts[response.status_code] = (
            status_counts.get(response.status_code, 0) + 1
        )
        if response.status_code not in expected_statuses:
            errors += 1
    if profiler is not None:
        profiler.disable()
    latencies.sort()
    return {
        "requests": requests,
        "errors": errors,
        "status_counts": {str(k): v for k, v in status_counts.items()},
        "us_mean": sum(latencies) / len(latencies),
        "us_p50": latencies[len(latencies) // 2],
        "us_p99": latencies[
            min(len(latencies) - 1, round(0.99 * (len(latencies) - 1)))
        ],
    }


async def _run_workload(
    name: str,
    client: ASGITestClient,
    requests: int,
    entries: int,
    profiler: cProfile.Profile | None = None,
) -> dict[str, Any]:
    basic = ASGITestClient.create_basic_authorization_headers(
        BASIC_USERNAME, BASIC_PASSWORD
    )

    if name == "options":
        factory = lambda: _make_request("OPTIONS", "/fs", basic, b"")  # noqa: E731
        expected = {200}
    elif name == "get-fs":
        factory = lambda: _make_request("GET", "/fs/4k.bin", basic, b"")  # noqa: E731
        expected = {200}
    elif name == "propfind-mem":
        factory = lambda: _make_request(  # noqa: E731
            "PROPFIND",
            f"/memory/dir-{entries}",
            {**basic, b"depth": b"1"},
            PROPFIND_ALLPROP_BODY.encode(),
        )
        expected = {207}
    elif name == "digest":
        # full handshake per cycle: 401 + challenge + authorized GET
        basic_get_headers = {b"accept-encoding": b"identity"}
        latencies: list[float] = []
        errors = 0
        for _ in range(requests):
            client.request = _make_request("GET", "/fs/4k.bin", basic_get_headers, b"")
            start = time.perf_counter()
            challenge_response = await client._call_method()
            if challenge_response.status_code != 401:
                errors += 1
                continue
            www_auth = challenge_response.headers.get(b"www-authenticate", b"")
            if not www_auth.startswith(b"Digest"):
                errors += 1
                continue
            auth = ASGITestClient.create_digest_authorization_headers(
                "GET",
                "/fs/4k.bin",
                www_auth.decode("latin-1"),
                DIGEST_USERNAME,
                password=DIGEST_PASSWORD,
                nc="00000001",
            )
            client.request = _make_request("GET", "/fs/4k.bin", auth, b"")
            final_response = await client._call_method()
            if final_response.status_code != 200:
                errors += 1
            latencies.append((time.perf_counter() - start) * 1e6)
        if not latencies:
            return {
                "requests": requests,
                "errors": errors,
                "status_counts": {},
                "us_mean": 0.0,
                "us_p50": 0.0,
                "us_p99": 0.0,
                "note": "no successful digest cycles",
            }
        latencies.sort()
        return {
            "requests": requests,
            "errors": errors,
            "status_counts": {},
            "us_mean": sum(latencies) / len(latencies),
            "us_p50": latencies[len(latencies) // 2],
            "us_p99": latencies[
                min(len(latencies) - 1, round(0.99 * (len(latencies) - 1)))
            ],
            "note": "cycles include the 401 challenge request",
        }
    else:
        msg = f"unknown workload {name!r}"
        raise ValueError(msg)

    return await _measure(client, factory, expected, requests, profiler)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="In-process ASGI benchmark")
    parser.add_argument("--requests", type=int, default=1000)
    parser.add_argument("--workload", default="all", choices=(*WORKLOADS, "all"))
    parser.add_argument("--variant", default="base")
    parser.add_argument("--entries", type=int, default=1000)
    parser.add_argument("--fs-dir", default=None, help="fixtures fs dir")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--cprofile-out", default=None)
    args = parser.parse_args(argv)

    fs_dir = Path(args.fs_dir) if args.fs_dir else _default_fs_dir()
    config = build_config_dict(
        args.variant, fixtures_fs_uri=f"file://{fs_dir}", digest=True
    )
    from asgi_webdav.config import generate_config_from_dict
    from asgi_webdav.constants import AppEntryParameters
    from asgi_webdav.server import get_asgi_app

    # keep get_asgi_app away from the repo .env: the app's EnvWizard reads
    # .env by cwd (see tests/test_server.py clean_env), so scrub the env AND
    # move to a neutral directory before building the app
    for key in [k for k in os.environ if k.startswith(("WEBDAV_", "SENTRY_"))]:
        del os.environ[key]
    os.chdir(tempfile.mkdtemp(prefix="asgi-webdav-inproc-"))

    app = get_asgi_app(
        AppEntryParameters(), generate_config_from_dict(config).to_dict()
    )
    client = BenchClient(app)

    names = WORKLOADS if args.workload == "all" else (args.workload,)
    # memory provider must exist before propfind-mem
    if any(n == "propfind-mem" for n in names):
        if not _seed_memory_dir(client, args.entries):
            print(
                "warning: memory seeding failed; propfind-mem results invalid",
                file=sys.stderr,
            )

    results: dict[str, Any] = {}
    for name in names:
        profiler = cProfile.Profile() if args.cprofile_out else None
        stats = asyncio.run(
            _run_workload(name, client, args.requests, args.entries, profiler)
        )
        if profiler is not None:
            stream = io.StringIO()
            pstats.Stats(profiler, stream=stream).sort_stats("tottime").print_stats(25)
            stats["trace"] = stream.getvalue()
        results[name] = stats

    payload = {
        "python": sys.version.split()[0],
        "requests": args.requests,
        "entries": args.entries,
        "results": results,
    }
    if args.json:
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    else:
        for name, stats in results.items():
            sys.stdout.write(
                f"{name:16s} {stats['us_mean']:10.1f} us/req mean, "
                f"p50 {stats['us_p50']:10.1f}, p99 {stats['us_p99']:10.1f}, "
                f"errors {stats['errors']}\n"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
