"""Linux leg via a dedicated lima VM (independent, removable)."""

from __future__ import annotations

import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

import click

from tools.common.env import REPO_ROOT
from tools.common.error import ToolError
from tools.common.lima import ensure_vm, vm_instance
from tools.common.proc import guest_argv, run_argv
from tools.perf.compat import collect_compat_entries, write_compat_summary
from tools.perf.fixtures import ensure_fixtures
from tools.perf.settings import PROBE_TIMEOUT, Settings
from tools.perf.summary import (
    collect_bench_samples,
    create_run_dir,
    load_or_init_meta,
    write_bench_summary,
)

VM_TIMEOUT = 600.0
VM_BUILD_TIMEOUT = 5400.0
VM_BENCH_TIMEOUT = 3600.0


def vm_cp_checked(
    local: Path, remote: str, vm_name: str, *, timeout: float = 120.0
) -> None:
    """limactl cp with verification — cp fails silently under socket races
    (e.g. right after a long guest shell session), leaving a stale remote
    file that then breaks the invoked script."""
    result = run_argv(
        ["limactl", "cp", str(local), f"{vm_name}:{remote}"], timeout=timeout
    )
    if result.returncode != 0:
        msg = f"limactl cp -> {remote!r} failed: {result.stdout[-200:]}"
        raise ToolError(msg)
    probe = run_argv(
        guest_argv(vm_name, ["sh", "-c", f"wc -c < {remote} 2>/dev/null || echo -1"]),
        timeout=60.0,
    )
    local_size = str(local.stat().st_size)
    if probe.stdout.strip() != local_size:
        msg = (
            f"limactl cp -> {remote!r} did not land (local {local_size} bytes, "
            f"remote {probe.stdout.strip()!r}); retry the command"
        )
        raise ToolError(msg)


@click.group()
def vm() -> None:
    """Linux leg via a dedicated lima VM (independent, removable)."""


@vm.command()
def status() -> None:
    settings = Settings.load()
    found = vm_instance(settings.vm_name, timeout=PROBE_TIMEOUT)
    if found is None:
        click.echo(f"{settings.vm_name}: not created")
        return
    click.echo(f"{found[0]}: {found[1]}")
    result = run_argv(
        guest_argv(
            settings.vm_name, ["sh", "-c", "ls /opt 2>/dev/null | tr '\\n' ' '"]
        ),
        timeout=PROBE_TIMEOUT,
    )
    click.echo(f"  built interpreters: {result.stdout.strip() or '(none yet)'}")


@vm.command()
def create() -> None:
    settings = Settings.load()
    ensure_vm(
        settings.vm_name,
        template=settings.vm_template,
        disk_gib=settings.vm_disk,
        create_timeout=VM_TIMEOUT,
        start_timeout=VM_TIMEOUT,
        probe_timeout=PROBE_TIMEOUT,
    )
    click.echo(f"vm ready: {settings.vm_name}")


@vm.command()
@click.option("--yes", is_flag=True, default=False)
def destroy(yes: bool) -> None:
    settings = Settings.load()
    if not yes:
        click.confirm(f"delete VM {settings.vm_name}?", abort=True)
    run_argv(["limactl", "delete", "-f", settings.vm_name], timeout=VM_TIMEOUT)
    click.echo("deleted")


_VM_SETUP_SH = """\
set -eu
export DEBIAN_FRONTEND=noninteractive
APT_MIRROR="{apt_mirror}"
if [ -n "$APT_MIRROR" ]; then
    sed -i "s|deb.debian.org|$APT_MIRROR|g" /etc/apt/sources.list.d/*.sources /etc/apt/sources.list 2>/dev/null || true
fi
sudo apt-get update -qq
sudo apt-get install -y -qq build-essential curl pkg-config libssl-dev zlib1g-dev \\
    libbz2-dev libreadline-dev libsqlite3-dev libffi-dev liblzma-dev \\
    libncurses-dev uuid-dev libzstd-dev linux-perf ca-certificates >/dev/null
cd /tmp
if [ ! -f Python-3.15.0.tgz ]; then
    curl -fsSLO https://www.python.org/ftp/python/3.15.0/Python-3.15.0.tgz
fi
if [ ! -d Python-3.15.0 ]; then
    tar xzf Python-3.15.0.tgz
fi
cd Python-3.15.0
build() {{
    NAME=$1; shift
    BIN="/opt/$NAME/bin/python3.15"
    [ "$NAME" != "py315" ] && BIN="/opt/$NAME/bin/python3.15t"
    if [ -x "$BIN" ] && [ -f "/opt/$NAME/.perf-built-v2" ]; then
        echo "skip build $NAME (exists)"
        return
    fi
    # marker v2: builds must include libzstd (compression.zstd C module)
    sudo rm -rf "/opt/$NAME"
    make distclean >/dev/null 2>&1 || true
    ./configure --prefix="/opt/$NAME" "$@" >/dev/null
    make -j"$(nproc)" >/dev/null
    # /opt is root-owned in the lima guest; passwordless sudo is available
    sudo make altinstall >/dev/null
    sudo touch "/opt/$NAME/.perf-built-v2"
    "$BIN" -c 'from compression import zstd; print("zstd ok")' >/dev/null
    echo "built $NAME"
}}
build py315
build py315t --disable-gil
# the JIT stencil compiler requires a pinned LLVM (clang-21), absent from
# Debian 13 — pull it from apt.llvm.org before the FT+JIT build
if ! command -v clang-21 >/dev/null 2>&1; then
    echo "deb [trusted=yes] http://apt.llvm.org/trixie/ llvm-toolchain-trixie-21 main" \\
        | sudo tee /etc/apt/sources.list.d/llvm-21.list >/dev/null
    sudo apt-get update -qq
    sudo apt-get install -y -qq clang-21 >/dev/null
fi
export PATH="/usr/lib/llvm-21/bin:$PATH"
build py315tjit --disable-gil --enable-experimental-jit=yes
/opt/py315/bin/python3.15 -c 'import sys; print("gil ok", sys.version)'
/opt/py315t/bin/python3.15t -c 'import sys; assert sys._is_gil_enabled() is False; print("ft ok")'
/opt/py315tjit/bin/python3.15t -c 'import sys; assert sys._is_gil_enabled() is False; print("ftjit ok")'
echo SETUP_OK
"""

_VM_VENV_SH = """\
set -eu
if [ ! -d ~/asgi-webdav ]; then
    echo "repo copy missing; run 'vm sync-repo' first" >&2
    exit 1
fi
mkvenv() {
    PY=$1; VENV=$2
    if [ ! -x "$VENV/bin/python" ]; then
        "$PY" -m venv "$VENV"
        "$VENV/bin/pip" -q install --upgrade pip
    fi
    :
    # test deps mirror requirements.d/test.txt minus pytest-cov (stripped
    # on purpose: coverage's C extension may lack FT wheels)
    "$VENV/bin/pip" -q install -e ~/asgi-webdav uvicorn \\
        pytest pytest-asyncio pytest-mock requests icecream httpx
    # three-tier optional deps: wheel -> source build -> skip (asyncio fallback)
    "$VENV/bin/pip" -q install uvloop httptools \\
        || "$VENV/bin/pip" -q --no-binary :all: install uvloop httptools \\
        || echo "note: uvloop/httptools unavailable for $VENV"
}
mkvenv /opt/py315/bin/python3.15 ~/venv-py315
mkvenv /opt/py315t/bin/python3.15t ~/venv-py315t
mkvenv /opt/py315tjit/bin/python3.15t ~/venv-py315tjit
echo VENV_OK
"""


@vm.command()
def setup() -> None:
    """Build GIL/FT/FT+JIT CPython 3.15 in the VM and create bench venvs."""
    settings = Settings.load()
    ensure_vm(
        settings.vm_name,
        template=settings.vm_template,
        disk_gib=settings.vm_disk,
        create_timeout=VM_TIMEOUT,
        start_timeout=VM_TIMEOUT,
        probe_timeout=PROBE_TIMEOUT,
    )
    stamp = int(time.time())
    script_path = Path("/tmp") / f"perf-vm-setup-{stamp}.sh"
    script_path.write_text(
        _VM_SETUP_SH.format(apt_mirror=settings.apt_mirror), encoding="utf-8"
    )
    run_argv(
        ["limactl", "cp", str(script_path), f"{settings.vm_name}:/tmp/setup.sh"],
        timeout=120.0,
    )
    click.echo("building interpreters in the VM (this can take ~30-60 min)...")
    result = run_argv(
        guest_argv(settings.vm_name, ["bash", "/tmp/setup.sh"]),
        timeout=VM_BUILD_TIMEOUT,
    )
    if result.returncode != 0 or "SETUP_OK" not in result.stdout:
        click.echo(f"setup failed:\n{result.stdout[-3000:]}")
        sys.exit(2)
    venv_path = Path("/tmp") / f"perf-vm-venv-{stamp}.sh"
    venv_path.write_text(_VM_VENV_SH, encoding="utf-8")
    vm_cp_checked(venv_path, "/tmp/venv.sh", settings.vm_name)
    click.echo("creating venvs + installing project...")
    result = run_argv(
        guest_argv(settings.vm_name, ["bash", "/tmp/venv.sh"]),
        timeout=VM_BUILD_TIMEOUT,
    )
    if "VENV_OK" not in result.stdout:
        click.echo(f"venv setup failed:\n{result.stdout[-3000:]}")
        sys.exit(2)
    script_path.unlink(missing_ok=True)
    venv_path.unlink(missing_ok=True)
    click.echo("vm setup complete (GIL/FT/FT+JIT)")


@vm.command("sync-repo")
def sync_repo() -> None:
    """Copy the repo (excluding venvs/git) and fixtures into the VM."""
    import tarfile

    settings = Settings.load()
    ensure_vm(
        settings.vm_name,
        template=settings.vm_template,
        disk_gib=settings.vm_disk,
        create_timeout=VM_TIMEOUT,
        start_timeout=VM_TIMEOUT,
        probe_timeout=PROBE_TIMEOUT,
    )
    ensure_fixtures(settings.fixtures_dir)
    stamp = int(time.time())
    repo_tar = Path("/tmp") / f"asgi-webdav-repo-{stamp}.tar.gz"
    skip_names = {".git", "output", "htmlcov", ".mypy_cache", ".pytest_cache", ".env"}
    with tarfile.open(repo_tar, "w:gz") as tar:
        for item in REPO_ROOT.iterdir():
            if item.name.startswith(".venv") or item.name in skip_names:
                continue
            tar.add(item, arcname=item.name)
    run_argv(
        ["limactl", "cp", str(repo_tar), f"{settings.vm_name}:~/repo.tar.gz"],
        timeout=300.0,
    )
    run_argv(
        guest_argv(
            settings.vm_name,
            [
                "sh",
                "-c",
                "rm -rf ~/asgi-webdav && mkdir ~/asgi-webdav && tar xzf ~/repo.tar.gz -C ~/asgi-webdav",
            ],
        ),
        timeout=300.0,
    )
    repo_tar.unlink(missing_ok=True)
    result = run_argv(
        guest_argv(settings.vm_name, ["sh", "-c", "mkdir -p ~/perf"]),
        timeout=60.0,
    )
    if result.returncode != 0:
        raise ToolError(f"mkdir ~/perf failed: {result.stdout[-200:]}")
    fixtures_tar = Path("/tmp") / f"perf-fixtures-{stamp}.tar.gz"
    with tarfile.open(fixtures_tar, "w:gz") as tar:
        tar.add(settings.fixtures_dir / "fs", arcname="fs")
    result = run_argv(
        [
            "limactl",
            "cp",
            str(fixtures_tar),
            f"{settings.vm_name}:~/perf/fixtures.tar.gz",
        ],
        timeout=300.0,
    )
    if result.returncode != 0:
        raise ToolError(f"fixtures cp failed: {result.stdout[-200:]}")
    result = run_argv(
        guest_argv(
            settings.vm_name,
            [
                "sh",
                "-c",
                "mkdir -p ~/perf/fixtures && tar xzf ~/perf/fixtures.tar.gz -C ~/perf/fixtures && ls ~/perf/fixtures/fs | head -3",
            ],
        ),
        timeout=300.0,
    )
    if result.returncode != 0:
        raise ToolError(f"fixtures extract failed: {result.stdout[-200:]}")
    fixtures_tar.unlink(missing_ok=True)
    click.echo(f"repo + fixtures synced into VM ({result.stdout.strip()})")


_VM_COMPAT_SH = """\
set -u
cd ~/asgi-webdav
export TOOLS_PERF_FIXTURES_DIR=$HOME/perf/fixtures
mkdir -p vm-results/compat
FAILED=0
$HOME/venv-py315/bin/python -m tools.perf.tasks.compat_one venv-py315 py315-lima {quick_flag} || FAILED=1
$HOME/venv-py315t/bin/python -m tools.perf.tasks.compat_one venv-py315t py315t-lima {quick_flag} || FAILED=1
$HOME/venv-py315tjit/bin/python -m tools.perf.tasks.compat_one venv-py315tjit py315tjit-lima {quick_flag} || FAILED=1
tar czf /tmp/perf-results-compat.tgz -C $HOME/asgi-webdav/vm-results compat
exit $FAILED
"""

_VM_BENCH_SH = """\
set -u
cd ~/asgi-webdav
export TOOLS_PERF_FIXTURES_DIR=$HOME/perf/fixtures
export TOOLS_PERF_DURATION={bench_duration}
export TOOLS_PERF_REPEATS={bench_repeats}
mkdir -p vm-results/bench
FAILED=0
$HOME/venv-py315/bin/python -m tools.perf.tasks.bench_one venv-py315 py315-lima {quick_flag} || FAILED=1
$HOME/venv-py315t/bin/python -m tools.perf.tasks.bench_one venv-py315t py315t-lima {quick_flag} || FAILED=1
$HOME/venv-py315tjit/bin/python -m tools.perf.tasks.bench_one venv-py315tjit py315tjit-lima {quick_flag} || FAILED=1
tar czf /tmp/perf-results-bench.tgz -C $HOME/asgi-webdav/vm-results bench
exit $FAILED
"""


@vm.command("compat")
@click.option("--quick", is_flag=True, default=False)
@click.option("--run-dir", default=None)
def vm_compat(quick: bool, run_dir: str | None) -> None:
    """Run the compat suite inside the VM for GIL/FT/FT+JIT."""
    settings = Settings.load()
    ensure_vm(
        settings.vm_name,
        template=settings.vm_template,
        disk_gib=settings.vm_disk,
        create_timeout=VM_TIMEOUT,
        start_timeout=VM_TIMEOUT,
        probe_timeout=PROBE_TIMEOUT,
    )
    the_run_dir = create_run_dir(settings, run_dir)
    the_run_dir.mkdir(parents=True, exist_ok=True)
    script = _VM_COMPAT_SH.format(quick_flag="--quick" if quick else "")
    load_or_init_meta(the_run_dir, settings)
    _run_vm_script_and_fetch(settings, script, the_run_dir, "compat")
    write_compat_summary(the_run_dir, collect_compat_entries(the_run_dir))
    click.echo(f"vm compat done; summary: {the_run_dir / 'compat' / 'summary.md'}")


@vm.command("bench")
@click.option("--quick", is_flag=True, default=False)
@click.option("--run-dir", default=None)
def vm_bench(quick: bool, run_dir: str | None) -> None:
    """Run the HTTP bench matrix inside the VM (GIL/FT/FT+JIT)."""
    settings = Settings.load()
    ensure_vm(
        settings.vm_name,
        template=settings.vm_template,
        disk_gib=settings.vm_disk,
        create_timeout=VM_TIMEOUT,
        start_timeout=VM_TIMEOUT,
        probe_timeout=PROBE_TIMEOUT,
    )
    the_run_dir = create_run_dir(settings, run_dir)
    the_run_dir.mkdir(parents=True, exist_ok=True)
    script = _VM_BENCH_SH.format(
        quick_flag="--quick" if quick else "",
        bench_duration=min(5.0, settings.duration),
        bench_repeats=min(3, settings.repeats),
    )
    load_or_init_meta(the_run_dir, settings)
    _run_vm_script_and_fetch(settings, script, the_run_dir, "bench")
    write_bench_summary(the_run_dir, collect_bench_samples(the_run_dir))
    click.echo(f"vm bench done; summary: {the_run_dir / 'summary.md'}")
    from tools.perf.baseline import try_auto_save_baseline

    try_auto_save_baseline(the_run_dir)


def _run_vm_script_and_fetch(
    settings: Settings, script: str, run_dir: Path, kind: str
) -> None:
    stamp = int(time.time())
    script_path = Path("/tmp") / f"perf-vm-{kind}-{stamp}.sh"
    script_path.write_text(script, encoding="utf-8")
    vm_cp_checked(script_path, f"/tmp/{kind}.sh", settings.vm_name)
    result = run_argv(
        guest_argv(settings.vm_name, ["bash", f"/tmp/{kind}.sh"]),
        timeout=VM_BENCH_TIMEOUT,
        passthrough=True,
    )
    # with passthrough the output went straight to the console (stdout is
    # None); only the exit code is available then
    if result.returncode != 0:
        click.echo(f"vm {kind} reported failure (exit {result.returncode})")
    # fetch results as a single tarball (the VM-side script packs it — args
    # after `limactl shell --` get no guest shell, so $HOME must expand there)
    tarball = f"/tmp/perf-results-{kind}.tgz"
    local_tgz = run_dir / f"vm-fetch-{kind}.tgz"
    run_argv(
        ["limactl", "cp", f"{settings.vm_name}:{tarball}", str(local_tgz)],
        timeout=600.0,
    )
    import tarfile

    if local_tgz.exists() and local_tgz.stat().st_size > 0:
        with tarfile.open(local_tgz, "r:gz") as tar:
            # each member stays under <kind>/... (packed with -C vm-results)
            tar.extractall(path=run_dir / "vm-fetch", filter="data")
        _merge_vm_results(run_dir / "vm-fetch" / kind, run_dir, kind)
        shutil.rmtree(run_dir / "vm-fetch", ignore_errors=True)
        local_tgz.unlink(missing_ok=True)
    else:
        click.echo(f"vm {kind}: no results tarball fetched")
    script_path.unlink(missing_ok=True)


def _merge_vm_results(local_dir: Path, run_dir: Path, kind: str) -> None:
    """Copy fetched VM result files into the host run-dir layout."""
    if not local_dir.exists():
        return
    for item in sorted(local_dir.rglob("*")):
        if not item.is_file():
            continue
        rel = item.relative_to(local_dir)
        target = run_dir / kind / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            item.read_text(encoding="utf-8", errors="replace"), encoding="utf-8"
        )


@vm.command()
@click.option("--duration", type=float, default=15.0)
def perf(duration: float) -> None:
    """perf-record the py315 server during a PROPFIND load (needs linux-perf)."""
    settings = Settings.load()
    ensure_vm(
        settings.vm_name,
        template=settings.vm_template,
        disk_gib=settings.vm_disk,
        create_timeout=VM_TIMEOUT,
        start_timeout=VM_TIMEOUT,
        probe_timeout=PROBE_TIMEOUT,
    )
    script = f"""\
set -eu
cd ~/asgi-webdav
sudo sysctl -w kernel.perf_event_paranoid=-1 >/dev/null 2>&1 || true
mkdir -p vm-results/perf
cat > /tmp/perf-config.toml <<EOF
[[account_mapping]]
username = "username"
password = "password"
permissions = ["+"]
admin = true

[[provider_mapping]]
prefix = "/fs"
uri = "file://$HOME/perf/fixtures/fs"
ignore_property_extra = false
EOF
PY=$HOME/venv-py315/bin/python
PYTHONPERFSUPPORT=1 perf record -F 199 -g -o vm-results/perf/perf.data \\
    -- $PY -m profiling.sampling run -m -r 5khz -d {duration} -a --binary \\
    -o vm-results/perf/profile.bin asgi_webdav -c /tmp/perf-config.toml \\
    -H 127.0.0.1 -P 8765 &
sleep 10
$PY -m tools.perf.tasks.driver --host 127.0.0.1 --port 8765 \\
    --method PROPFIND --path /fs/dir-1000 -c 4 --duration {duration} \\
    --auth username:password --header 'Content-Type: application/xml' \\
    --body '<?xml version="1.0" encoding="utf-8"?><D:propfind xmlns:D="DAV:"><D:allprop/></D:propfind>' \\
    > vm-results/perf/load.json
wait
perf script -i vm-results/perf/perf.data > vm-results/perf/perf.script 2>/dev/null || true
echo VM_PERF_OK
"""
    stamp = int(time.time())
    script_path = Path("/tmp") / f"perf-vm-perf-{stamp}.sh"
    script_path.write_text(script, encoding="utf-8")
    vm_cp_checked(script_path, "/tmp/perf.sh", settings.vm_name)
    result = run_argv(
        guest_argv(settings.vm_name, ["bash", "/tmp/perf.sh"]),
        timeout=VM_BENCH_TIMEOUT,
    )
    click.echo(result.stdout[-2000:] if result.stdout else "(no output)")
    # fetch the artifacts (they only exist inside the guest)
    local_perf = (
        settings.log_dir / f"vm-perf-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    )
    local_perf.mkdir(parents=True, exist_ok=True)
    for name in ("perf.data", "perf.script", "load.json"):
        fetched = run_argv(
            [
                "limactl",
                "cp",
                f"{settings.vm_name}:~/asgi-webdav/vm-results/perf/{name}",
                str(local_perf / name),
            ],
            timeout=300.0,
        )
        if fetched.returncode == 0:
            click.echo(f"fetched: {local_perf / name}")
    script_path.unlink(missing_ok=True)
