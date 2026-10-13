"""Micro-benchmarks for asgi-webdav per-request CPU hot spots.

Run by hand, or through the perf tool which executes it under each target
interpreter::

    .venv/bin/python -m tools.perf.tasks.micro            # human-readable table
    .venv/bin/python -m tools.perf.tasks.micro --json     # machine-readable
    .venv/bin/python -m tools.perf.tasks.micro --trace    # + cProfile call counts

Numbers are min-of-5 timeit (lower is better). Shapes mirror the real
per-request code paths; see the comment on each bench for the source
reference. Requires the project importable (installed venv or cwd=repo root).
"""

from __future__ import annotations

import argparse
import cProfile
import hashlib
import io
import json
import pstats
import re
import sys
import timeit
import tracemalloc
import urllib.parse
from collections.abc import Callable
from pathlib import Path
from typing import TextIO

from asgi_webdav.constants import DAVPath, DAVTime
from asgi_webdav.helpers import generate_etag, get_dict_from_xml, get_xml_from_dict

BENCH_NUMBER = 20_000
BENCH_REPEAT = 5
PROPFIND_ENTRIES = 1_000

# A typical allprop-lite PROPFIND request body (shape of request.py:586 parse)
PROPFIND_REQUEST_BODY = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<D:propfind xmlns:D="DAV:">'
    "<D:prop><D:displayname/><D:resourcetype/><D:getcontentlength/>"
    "<D:getlastmodified/><D:creationdate/><D:_supportedlock/></D:prop>"
    "</D:propfind>"
)


def _build_propfind_response_shape(entries: int) -> dict[str, object]:
    """Mirror of provider/common.py:440-533 create_propfind_response output."""
    response: list[dict[str, object]] = []
    for i in range(entries):
        found_property: dict[str, object] = {
            "D:displayname": f"entry-{i:04d}.txt",
            "D:getcontentlength": 4096,
            "D:getlastmodified": "Mon, 01 Jan 2026 00:00:00 GMT",
            "D:creationdate": "2026-01-01T00:00:00Z",
            "D:resourcetype": None,
        }
        response.append(
            {
                "D:href": urllib.parse.quote(f"/fs/dir-{entries}/entry-{i:04d}.txt"),
                "D:propstat": [
                    {
                        "D:prop": found_property,
                        "D:lockdiscovery": None,
                        "D:status": "HTTP/1.1 200 OK",
                    }
                ],
            }
        )
    return {"D:multistatus": {"@xmlns:D": "DAV:", "D:response": response}}


def _bench(
    label: str,
    fn: Callable[[], object],
    number: int = BENCH_NUMBER,
) -> tuple[str, float]:
    best = min(timeit.repeat(fn, number=number, repeat=BENCH_REPEAT)) / number
    return label, best * 1e6


def run_benches() -> dict[str, float]:
    results: dict[str, float] = {}

    # --- request path shapes -------------------------------------------------
    prefix = DAVPath("/fs")
    label, us = _bench(
        "davpath.construct", lambda: DAVPath("/fs/dir-1000/entry-0001.txt")
    )
    results[label] = us
    label, us = _bench("davpath.add_child", lambda: prefix.add_child("entry-0001.txt"))
    results[label] = us

    # --- auth: check_paths_permission (constants.py:726, un-precompiled) -----
    path_raw = "/fs/dir-1000/entry-0001.txt"
    patterns = ["^/fs/", "^/other/"]
    pattern = patterns[0]
    label, us = _bench(
        "auth.re_match_single",
        lambda: re.match(pattern, path_raw),
    )
    results[label] = us

    def permission_shape() -> bool:
        # per-request cost of one allow pattern against one path
        return any(m is not None for m in (re.match(p, path_raw) for p in patterns))

    label, us = _bench("auth.check_paths_permission_shape", permission_shape)
    results[label] = us

    # --- compression match (response.py:130-190 shape: 2x re.match) ----------
    accept = "gzip, deflate, br, zstd"

    def compression_match_shape() -> bool:
        m1 = re.match(r"(?i)zstd", accept)
        m2 = re.match(r"(?i)(?:x-gzip|gzip)", accept)
        return m1 is not None or m2 is not None

    label, us = _bench("response.compression_match_shape", compression_match_shape)
    results[label] = us

    # --- property data (constants.py:355 DAVTime, helpers.py:44 etag) --------
    timestamp = 1_767_225_600.0

    def davtime_full() -> str:
        t = DAVTime(timestamp)
        return f"{t.http_date}|{t.iso_8601}"

    label, us = _bench("property.davtime_http_date_iso", davtime_full)
    results[label] = us
    label, us = _bench("property.generate_etag", lambda: generate_etag(4096, timestamp))
    results[label] = us
    label, us = _bench(
        "property.quote_href",
        lambda: urllib.parse.quote("/fs/dir-1000/entry-0001.txt"),
    )
    results[label] = us

    # md5 baseline for etag comparison
    def md5_shape() -> str:
        return hashlib.md5(f"{4096}{timestamp}".encode()).hexdigest()

    label, us = _bench("property.etag_md5_raw", md5_shape)
    results[label] = us

    # --- xmltodict round trips (helpers.py:126/134) --------------------------
    response_shape = _build_propfind_response_shape(PROPFIND_ENTRIES)
    number_unparse = max(20, BENCH_NUMBER // (PROPFIND_ENTRIES // 10))
    label, us = _bench(
        f"xml.unparse_propfind_{PROPFIND_ENTRIES}",
        lambda: get_xml_from_dict(response_shape),
        number=number_unparse,
    )
    results[label] = us

    label, us = _bench(
        "xml.parse_propfind_request",
        lambda: get_dict_from_xml(PROPFIND_REQUEST_BODY.encode("utf-8"), "propfind"),
    )
    results[label] = us

    # --- optional: DAVRequest construction (tests/kits) ----------------------
    try:
        from tests.kits.asgi import create_dav_request_object
    except ImportError:
        print("skip: davrequest.construct (tests.kits not importable)")
    else:
        basic = "Basic dXNlcm5hbWU6cGFzc3dvcmQ="
        label, us = _bench(
            "request.construct",
            lambda: create_dav_request_object(
                method="GET",
                path="/fs/4k.bin",
                headers={"Authorization": basic, "Depth": "1"},
            ),
        )
        results[label] = us

    return results


def run_memory_check() -> dict[str, float]:
    """tracemalloc over the PROPFIND unparse shape (retention sanity)."""
    shape = _build_propfind_response_shape(PROPFIND_ENTRIES)
    tracemalloc.start()
    for _ in range(3):
        get_xml_from_dict(shape)
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {"current_mb": current / 1e6, "peak_mb": peak / 1e6}


def run_trace() -> str:
    """cProfile call counts for the heaviest single shape (unparse 1000)."""
    shape = _build_propfind_response_shape(PROPFIND_ENTRIES)
    profiler = cProfile.Profile()
    profiler.enable()
    for _ in range(20):
        get_xml_from_dict(shape)
    profiler.disable()
    stream = io.StringIO()
    stats = pstats.Stats(profiler, stream=stream)
    stats.sort_stats("tottime").print_stats(25)
    return stream.getvalue()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="asgi-webdav micro benchmarks")
    parser.add_argument("--json", action="store_true", help="emit JSON")
    parser.add_argument("--json-out", help="write JSON to this path as well")
    parser.add_argument("--trace", action="store_true", help="add cProfile top-25")
    parser.add_argument(
        "--memory", action="store_true", default=True, help="include tracemalloc"
    )
    args = parser.parse_args(argv)

    import platform

    results = run_benches()
    payload: dict[str, object] = {
        "python": sys.version.split()[0],
        "implementation": platform.python_implementation(),
        "bench_us_per_op": results,
    }
    if args.memory:
        payload["memory"] = run_memory_check()
    if args.trace:
        payload["trace"] = run_trace()

    if args.json:
        text = json.dumps(payload, indent=2)
        if args.json_out:
            Path(args.json_out).write_text(text + "\n", encoding="utf-8")
        sys.stdout.write(text + "\n")
    else:
        out: TextIO = sys.stdout
        out.write(f"python {payload['python']} ({payload['implementation']})\n")
        for name, us in results.items():
            out.write(f"{name:48s} {us:10.3f} us/op\n")
        memory = payload.get("memory")
        if isinstance(memory, dict):
            out.write(
                f"\nPROPFIND unparse tracemalloc: "
                f"{memory['current_mb']:.3f} MB current, "
                f"{memory['peak_mb']:.3f} MB peak\n"
            )
        if args.trace:
            trace = payload.get("trace")
            if isinstance(trace, str):
                out.write("\n" + trace)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
