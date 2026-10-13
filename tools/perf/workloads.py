"""Benchmark workload table (request shapes per isolated hot spot)."""

from __future__ import annotations

from dataclasses import dataclass

PROPFIND_ALLPROP_BODY = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<D:propfind xmlns:D="DAV:"><D:allprop/></D:propfind>'
)
PROPFIND_BASIC_BODY = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<D:propfind xmlns:D="DAV:"><D:prop>'
    "<D:displayname/><D:resourcetype/><D:getcontentlength/>"
    "</D:prop></D:propfind>"
)


@dataclass(frozen=True)
class Workload:
    name: str
    method: str
    path: str
    body: str | None = None
    content_type: str | None = None
    count_mode: int | None = None  # when set, run -n instead of -z
    headers: tuple[tuple[str, str], ...] = ()


WORKLOAD_TABLE: dict[str, Workload] = {
    w.name: w
    for w in (
        Workload("options", "OPTIONS", "/"),
        Workload("head-4k", "HEAD", "/fs/4k.bin"),
        Workload("get-4k", "GET", "/fs/4k.bin"),
        Workload("get-64m", "GET", "/fs/64m.bin", count_mode=100),
        Workload(
            "put-4k",
            "PUT",
            "/fs/put-4k.bin",
            body="a" * 4096,
            content_type="application/octet-stream",
        ),
        Workload(
            "propfind-0",
            "PROPFIND",
            "/fs/dir-100/entry-0000.txt",
            body=PROPFIND_ALLPROP_BODY,
            content_type="application/xml",
        ),
        Workload(
            "propfind-1-10",
            "PROPFIND",
            "/fs/dir-10",
            body=PROPFIND_ALLPROP_BODY,
            content_type="application/xml",
            headers=(("Depth", "1"),),
        ),
        Workload(
            "propfind-1-100",
            "PROPFIND",
            "/fs/dir-100",
            body=PROPFIND_ALLPROP_BODY,
            content_type="application/xml",
            headers=(("Depth", "1"),),
        ),
        Workload(
            "propfind-1-1000",
            "PROPFIND",
            "/fs/dir-1000",
            body=PROPFIND_ALLPROP_BODY,
            content_type="application/xml",
            headers=(("Depth", "1"),),
        ),
        Workload(
            "propfind-basic-1000",
            "PROPFIND",
            "/fs/dir-1000",
            body=PROPFIND_BASIC_BODY,
            content_type="application/xml",
            headers=(("Depth", "1"),),
        ),
        Workload(
            "propfind-mem-1000",
            "PROPFIND",
            "/memory/dir-1000",
            body=PROPFIND_ALLPROP_BODY,
            content_type="application/xml",
            headers=(("Depth", "1"),),
        ),
        Workload(
            "copy-4k",
            "COPY",
            "/fs/4k.bin",
        ),
    )
}

DEFAULT_WORKLOADS: tuple[str, ...] = (
    "options",
    "head-4k",
    "get-4k",
    "get-64m",
    "put-4k",
    "propfind-0",
    "propfind-1-10",
    "propfind-1-100",
    "propfind-1-1000",
)
QUICK_WORKLOADS: tuple[str, ...] = ("get-4k", "propfind-1-100")


# ---------------------------------------------------------------------------
# bench samples
