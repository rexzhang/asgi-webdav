"""Benchmark fixture tree generation."""

from __future__ import annotations

from pathlib import Path


def ensure_fixtures(fixtures_dir: Path, *, recreate: bool = False) -> Path:
    fs_dir = fixtures_dir / "fs"
    marker = fs_dir / "4k.bin"
    if marker.exists() and not recreate:
        return fs_dir
    fs_dir.mkdir(parents=True, exist_ok=True)
    block_4k = bytes(range(256)) * 16
    (fs_dir / "4k.bin").write_bytes(block_4k)
    (fs_dir / "64m.bin").write_bytes(block_4k * 16 * 1024)
    (fs_dir / "put-4k.bin").write_bytes(b"a" * 4096)
    for count in (10, 100, 1000):
        target = fs_dir / f"dir-{count}"
        target.mkdir(parents=True, exist_ok=True)
        for i in range(count):
            (target / f"entry-{i:04d}.txt").write_bytes(f"entry-{i}\n".encode() * 4)
    return fs_dir


# ---------------------------------------------------------------------------
# server subprocess management
