# DAVPath micro-benchmarks, run by hand:
#   .venv/bin/python tests/by_hand/bench_dav_path.py
# Numbers are min-of-5 timeit, so lower is better.

import timeit
import tracemalloc
from collections.abc import Callable

from asgi_webdav.constants import DAVPath


def bench(label: str, fn: Callable[[], object], number: int = 200_000) -> None:
    best = min(timeit.repeat(fn, number=number, repeat=5)) / number
    print(f"{label:56s} {best * 1e6:10.3f} us/op")


def main() -> None:
    prefix_a = DAVPath("/dir1")
    prefix_ab = DAVPath("/dir1/dir2")
    request_path = DAVPath("/dir1/dir2/file.txt")
    entries = [f"entry-{i:04d}.txt" for i in range(10_000)]

    bench(
        "construct DAVPath('/dir1/dir2/file.txt')",
        lambda: DAVPath("/dir1/dir2/file.txt"),
    )
    bench("first .raw access (join)", lambda: DAVPath("/a/b/c").raw, number=100_000)
    bench("cached .raw access", lambda: request_path.raw)
    eq_left = DAVPath("/a/b")
    eq_right = DAVPath("a/b/")
    eq_other = DAVPath("/a/b/c")
    bench("__eq__ equal (pre-built instances)", lambda: eq_left == eq_right)
    bench("__eq__ not equal (pre-built instances)", lambda: eq_left == eq_other)
    bench("is_parent_of (non-root self)", lambda: prefix_ab.is_parent_of(request_path))
    bench(
        "is_parent_of_or_is_self (non-root self)",
        lambda: prefix_ab.is_parent_of_or_is_self(request_path),
    )
    bench(
        "root.is_parent_of_or_is_self",
        lambda: DAVPath("/").is_parent_of_or_is_self(request_path),
    )
    bench("add_child single segment str", lambda: prefix_a.add_child("file.txt"))
    bench(
        "add_child multi segment str (fallback)",
        lambda: prefix_a.add_child("dir2/file.txt"),
    )
    bench("parent repeat access", lambda: request_path.parent)

    # match_provider shape: 3 prefixes scanned per request
    prefixes = [DAVPath("/"), DAVPath("/dir1"), DAVPath("/dir1/dir2")]
    bench(
        "match_provider shape (3 prefixes x 1 request)",
        lambda: next(p for p in prefixes if p.is_parent_of_or_is_self(request_path)),
        number=100_000,
    )

    # PROPFIND shape: add_child + first .raw + dict insert per entry
    def propfind_shape() -> int:
        out: dict[DAVPath, int] = {}
        for name in entries:
            child = prefix_a.add_child(name)
            out[child] = len(child.raw)
        return len(out)

    bench("PROPFIND shape (10k entries per pass)", propfind_shape, number=5)

    # memory sanity: no unbounded retention across passes
    tracemalloc.start()
    for _ in range(3):
        propfind_shape()
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(
        f"\n{'PROPFIND shape tracemalloc (after 3 passes)':56s} {current / 1e6:10.3f} MB current, {peak / 1e6:10.3f} MB peak"
    )


if __name__ == "__main__":
    main()
