"""Run WebDAV litmus compliance tests against a running ASGI-WebDAV server.

The tool drives a dedicated Lima VM (created automatically on first use,
Debian by default): litmus is installed inside the VM, and each test target
is reached through ``host.lima.internal`` so the server must be bound to
``0.0.0.0`` on the macOS host. The server itself is NOT managed here — start
it before invoking ``run``::

    python -m asgi_webdav -c examples/config/litmus.toml -H 0.0.0.0
    .venv/bin/python -m tools.litmus_cli run

Machine-local configuration comes from the repo-root ``.env`` (gitignored),
every variable prefixed with ``TOOLS_``. All variables are optional; the
defaults match ``examples/config/litmus.toml``:

    TOOLS_LITMUS_VM_NAME       lima VM name          (asgi-webdav-tools-d13)
    TOOLS_LITMUS_VM_TEMPLATE   lima VM template      (template:debian)
    TOOLS_LITMUS_VM_DISK       VM disk size in GiB   (10)
    TOOLS_LITMUS_APT_MIRROR    apt mirror host for   ()
                               the guest, empty =
                               deb.debian.org
    TOOLS_LITMUS_SERVER_PORT   host server port      (8000)
    TOOLS_LITMUS_GUEST_HOST    guest->host hostname  (host.lima.internal)
    TOOLS_LITMUS_TARGETS       target names          (fs-basic,fs-digest,
                                                     memory-basic,memory-digest)
    TOOLS_LITMUS_SUITES        litmus suites via the ()  basic copymove props
                               $TESTS env var, empty =   locks http
                               run all suites
    TOOLS_LITMUS_LOG_DIR       log dir, empty =      (tests/test_zone/litmus)
                               disable logging

Per-target overrides follow the pattern
``TOOLS_LITMUS_TARGET_{NAME}_{URL|USERNAME|PASSWORD}`` where ``{NAME}`` is
the upper-cased target name with ``-`` replaced by ``_``. Precedence:
``.env`` file > process environment > hardcoded default.

Exit codes: 0 = all targets passed, 1 = at least one litmus failure,
2 = infrastructure error (limactl/apt/preflight), 130 = interrupted.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

import click
from dotenv import dotenv_values

REPO_ROOT = Path(__file__).resolve().parent.parent
DOTENV_PATH = REPO_ROOT / ".env"

VM_TIMEOUT = 600.0
APT_TIMEOUT = 300.0
PROBE_TIMEOUT = 30.0

DEFAULT_VM_NAME = "asgi-webdav-tools-d13"
DEFAULT_VM_TEMPLATE = "template:debian"
DEFAULT_VM_DISK = 10
DEFAULT_SERVER_PORT = 8000
DEFAULT_GUEST_HOST = "host.lima.internal"
DEFAULT_LOG_DIR = "tests/test_zone/litmus"

PREFLIGHT_HINT = """\
The WebDAV server must be reachable from inside the lima VM:
  - start the server bound to all interfaces, e.g.:
      python -m asgi_webdav -c examples/config/litmus.toml -H 0.0.0.0
  - the VM reaches the macOS host via the configured guest host name
  - macOS may show a firewall prompt for python on first 0.0.0.0 bind"""

_DOTENV: Mapping[str, str | None] | None = None


class ToolError(Exception):
    """Infrastructure failure that maps to exit code 2."""


@dataclass(frozen=True)
class Target:
    name: str
    url_path: str
    username: str
    password: str


DEFAULT_TARGETS: tuple[Target, ...] = (
    Target("fs-basic", "/provider/fs", "username", "password"),
    Target("fs-digest", "/provider/fs", "username-digest", "password"),
    Target("memory-basic", "/provider/memory", "username", "password"),
    Target("memory-digest", "/provider/memory", "username-digest", "password"),
)


@dataclass(frozen=True)
class Settings:
    vm_name: str
    vm_template: str
    vm_disk: int
    apt_mirror: str
    server_port: int
    guest_host: str
    suites: tuple[str, ...]
    log_dir: Path | None
    targets: tuple[Target, ...]

    @classmethod
    def load(
        cls,
        *,
        port: int | None = None,
        log_dir: str | None = None,
        no_log: bool = False,
        target_names: Sequence[str] = (),
        suites: Sequence[str] = (),
    ) -> Settings:
        resolved_port = (
            port
            if port is not None
            else _env_int("TOOLS_LITMUS_SERVER_PORT", DEFAULT_SERVER_PORT)
        )
        resolved_suites = tuple(suites) or _env_list("TOOLS_LITMUS_SUITES")
        requested_names = (
            tuple(target_names)
            or _env_list("TOOLS_LITMUS_TARGETS")
            or _default_target_names()
        )
        if no_log:
            resolved_log_dir = None
        else:
            resolved_log_dir = _resolve_log_dir(
                log_dir
                if log_dir is not None
                else _env("TOOLS_LITMUS_LOG_DIR", DEFAULT_LOG_DIR)
            )
        return cls(
            vm_name=_env("TOOLS_LITMUS_VM_NAME", DEFAULT_VM_NAME),
            vm_template=_env("TOOLS_LITMUS_VM_TEMPLATE", DEFAULT_VM_TEMPLATE),
            vm_disk=_env_int("TOOLS_LITMUS_VM_DISK", DEFAULT_VM_DISK),
            apt_mirror=_env("TOOLS_LITMUS_APT_MIRROR"),
            server_port=resolved_port,
            guest_host=_env("TOOLS_LITMUS_GUEST_HOST", DEFAULT_GUEST_HOST),
            suites=resolved_suites,
            log_dir=resolved_log_dir,
            targets=_resolve_targets(requested_names),
        )


@dataclass
class SuiteResult:
    name: str
    run: int | None = None
    passed: int | None = None
    failed: int | None = None

    @property
    def complete(self) -> bool:
        return self.run is not None

    @property
    def failed_count(self) -> int:
        return self.failed or 0


@dataclass
class TargetResult:
    target: Target
    suites: list[SuiteResult]
    exit_code: int

    @property
    def ok(self) -> bool:
        # The per-suite summary lines are authoritative; if nothing was parsed
        # at all the run is treated as failed even on exit code 0.
        return (
            bool(self.suites)
            and self.exit_code == 0
            and all(s.failed_count == 0 for s in self.suites)
        )

    @property
    def total_failed(self) -> int:
        return sum(s.failed_count for s in self.suites)


def _dotenv() -> Mapping[str, str | None]:
    global _DOTENV
    if _DOTENV is None:
        _DOTENV = dotenv_values(DOTENV_PATH) if DOTENV_PATH.exists() else {}
    return _DOTENV


def _env(key: str, default: str = "") -> str:
    # .env file wins over the process environment, both win over the default
    # (same file-wins precedence as fabfile.py).
    value = _dotenv().get(key)
    if value is None:
        value = os.environ.get(key)
    return default if value is None else value


def _env_int(key: str, default: int) -> int:
    raw = _env(key, str(default))
    try:
        return int(raw)
    except ValueError:
        msg = f"env var {key!r} must be an integer, got {raw!r}"
        raise ToolError(msg) from None


def _env_list(key: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in _env(key).split(",") if part.strip())


def _default_target_names() -> tuple[str, ...]:
    return tuple(target.name for target in DEFAULT_TARGETS)


def _target_env_prefix(name: str) -> str:
    return f"TOOLS_LITMUS_TARGET_{name.upper().replace('-', '_')}_"


def _resolve_targets(names: tuple[str, ...]) -> tuple[Target, ...]:
    targets: list[Target] = []
    known = ", ".join(_default_target_names())
    for name in names:
        defaults = next((t for t in DEFAULT_TARGETS if t.name == name), None)
        prefix = _target_env_prefix(name)
        env_url = _env(f"{prefix}URL")
        env_username = _env(f"{prefix}USERNAME")
        env_password = _env(f"{prefix}PASSWORD")
        if defaults is None and not (env_url or env_username or env_password):
            msg = f"unknown target {name!r}, known targets: {known} (or define {prefix}URL/{prefix}USERNAME/{prefix}PASSWORD)"
            raise ToolError(msg)
        target = Target(
            name=name,
            url_path=env_url or (defaults.url_path if defaults else ""),
            username=env_username or (defaults.username if defaults else ""),
            password=env_password or (defaults.password if defaults else ""),
        )
        if not (target.url_path and target.username and target.password):
            msg = f"target {name!r} is incomplete, set {prefix}URL, {prefix}USERNAME and {prefix}PASSWORD"
            raise ToolError(msg)
        targets.append(target)
    if not targets:
        msg = "no test targets configured"
        raise ToolError(msg)
    return tuple(targets)


def _resolve_log_dir(raw: str) -> Path | None:
    if raw == "":
        return None
    path = Path(raw)
    return path if path.is_absolute() else REPO_ROOT / path


def run_argv(
    argv: list[str],
    *,
    timeout: float | None = None,
    passthrough: bool = False,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            argv,
            timeout=timeout,
            text=True,
            stdout=None if passthrough else subprocess.PIPE,
            stderr=None if passthrough else subprocess.STDOUT,
        )
    except FileNotFoundError as e:
        msg = f"command not found: {argv[0]}"
        raise ToolError(msg) from e
    except subprocess.TimeoutExpired as e:
        msg = f"command timed out after {timeout}s: {shlex.join(argv)}"
        raise ToolError(msg) from e


def guest_argv(vm_name: str, args: Sequence[str]) -> list[str]:
    # limactl (v2.x) forwards each arg verbatim to the guest command — no
    # guest shell re-parses the line, so args must NOT be quoted here.
    return ["limactl", "shell", vm_name, "--", *args]


def vm_instance(vm_name: str) -> tuple[str, str] | None:
    """Return (instance name, status) for the exact instance, if it exists."""
    result = run_argv(["limactl", "list", "--json"], timeout=PROBE_TIMEOUT)
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data: dict[str, Any] = json.loads(line)
        except json.JSONDecodeError:
            continue
        if data.get("name") == vm_name:
            return vm_name, str(data.get("status"))
    return None


def ensure_vm(settings: Settings, *, allow_create: bool = True) -> str:
    found = vm_instance(settings.vm_name)
    if found is None:
        create_argv = [
            "limactl",
            "create",
            "--plain",
            "--disk",
            str(settings.vm_disk),
            "--name",
            settings.vm_name,
            settings.vm_template,
        ]
        if not allow_create:
            msg = f"lima VM {settings.vm_name!r} does not exist and creation is disabled, create it with: {shlex.join(create_argv)}"
            raise ToolError(msg)
        click.secho(
            f"Creating lima VM {settings.vm_name!r} from {settings.vm_template!r} ...",
            fg="cyan",
        )
        result = run_argv(create_argv, timeout=VM_TIMEOUT, passthrough=True)
        if result.returncode != 0:
            msg = f"limactl create failed with exit code {result.returncode}"
            raise ToolError(msg)
        found = vm_instance(settings.vm_name)
        if found is None:
            msg = f"limactl create finished but no instance for {settings.vm_name!r} was found"
            raise ToolError(msg)
    instance, status = found
    if status != "Running":
        click.secho(f"Starting lima VM {instance!r} ...", fg="cyan")
        result = run_argv(
            ["limactl", "start", instance], timeout=VM_TIMEOUT, passthrough=True
        )
        if result.returncode != 0:
            msg = f"limactl start failed with exit code {result.returncode}"
            raise ToolError(msg)
    click.secho(f"lima VM {instance!r} is ready.", fg="cyan")
    return instance


def _apply_apt_mirror(vm_name: str, mirror_host: str) -> None:
    # Same approach as the rpi-builder VM provisioning: point the guest apt
    # sources at a nearby mirror before any network access. Debian 13 cloud
    # images resolve sources through /etc/apt/mirrors/*.list URL files; older
    # layouts embed deb.debian.org in the sources files instead.
    base = f"https://{mirror_host}"
    script = (
        "if [ -f /etc/apt/mirrors/debian.list ]; then "
        f"printf '%s\\n' '{base}/debian' > /etc/apt/mirrors/debian.list; fi; "
        "if [ -f /etc/apt/mirrors/debian-security.list ]; then "
        f"printf '%s\\n' '{base}/debian-security' > /etc/apt/mirrors/debian-security.list; fi; "
        "for f in /etc/apt/sources.list /etc/apt/sources.list.d/*.list "
        "/etc/apt/sources.list.d/*.sources; do "
        '[ -f "$f" ] && sed -i.bak '
        f"'s#//deb.debian.org#//{mirror_host}#g' \"$f\"; "
        "done; true"
    )
    result = run_argv(
        guest_argv(vm_name, ["sudo", "sh", "-c", script]), timeout=PROBE_TIMEOUT
    )
    if result.returncode != 0:
        msg = f"failed to apply apt mirror {mirror_host!r}: {result.stdout.strip()}"
        raise ToolError(msg)


def ensure_litmus(vm_name: str, settings: Settings) -> None:
    probe = run_argv(
        guest_argv(vm_name, ["which", "litmus"]),
        timeout=PROBE_TIMEOUT,
    )
    if probe.returncode == 0 and probe.stdout.strip():
        click.secho("litmus is already installed in the VM.", fg="cyan")
        return
    if settings.apt_mirror:
        click.secho(f"Applying apt mirror {settings.apt_mirror!r} ...", fg="cyan")
        _apply_apt_mirror(vm_name, settings.apt_mirror)
    # A previously timed-out apt-get may still hold the apt lock in the guest
    # (killing limactl does not reach the remote process) — clear it. Return
    # code 1 means no process matched, which is fine.
    run_argv(
        guest_argv(vm_name, ["sudo", "pkill", "-x", "apt-get"]), timeout=PROBE_TIMEOUT
    )
    click.secho("Installing litmus in the VM via apt ...", fg="cyan")
    for argv in (
        ["sudo", "apt-get", "update"],
        ["sudo", "apt-get", "install", "-y", "litmus", "curl"],
    ):
        result = run_argv(
            guest_argv(vm_name, argv), timeout=APT_TIMEOUT, passthrough=True
        )
        if result.returncode != 0:
            msg = f"apt install failed with exit code {result.returncode}: {shlex.join(argv)}"
            raise ToolError(msg)


def target_base_url(settings: Settings, target: Target) -> str:
    return f"http://{settings.guest_host}:{settings.server_port}{target.url_path}"


def preflight_from_guest(vm_name: str, url: str) -> None:
    # No curl -f here: an anonymous GET on a DAV root answers 401, which
    # counts as reachable — any 3-digit status code proves the TCP+HTTP path.
    argv = guest_argv(
        vm_name, ["curl", "-sS", "-o", "/dev/null", "-w", "%{http_code}", url]
    )
    result = run_argv(argv, timeout=PROBE_TIMEOUT)
    body = result.stdout.strip()
    if result.returncode == 0 and re.fullmatch(r"\d{3}", body):
        click.secho(f"Preflight OK: {url} -> HTTP {body}", fg="cyan")
        return
    detail = body if body else f"curl exit code {result.returncode}"
    msg = f"target not reachable from VM: GET {url} -> {detail}\n{PREFLIGHT_HINT}"
    raise ToolError(msg)


_SUITE_RE = re.compile(r"^-> running [`'](\w+)['`]:")
_SUMMARY_RE = re.compile(r"of (\d+) tests run: (\d+) passed, (\d+) failed")
_FAIL_TOKEN_RE = re.compile(r"\bFAIL\b")


def _parse_line(result: TargetResult, line: str) -> None:
    match = _SUITE_RE.match(line)
    if match is not None:
        result.suites.append(SuiteResult(name=match.group(1)))
        return
    if not result.suites:
        return
    current = result.suites[-1]
    match = _SUMMARY_RE.search(line)
    if match is not None:
        current.run = int(match.group(1))
        current.passed = int(match.group(2))
        current.failed = int(match.group(3))
        return
    # Fallback for output without per-suite summary lines: count FAIL tokens.
    if not current.complete and _FAIL_TOKEN_RE.search(line):
        current.failed = (current.failed or 0) + 1


def _stream_child_lines(proc: subprocess.Popen[str]) -> Iterator[str]:
    # litmus prints "press Return to continue..." WITHOUT a trailing newline,
    # so iterate character-wise and split lines ourselves.
    assert proc.stdout is not None
    buffer = ""
    while True:
        char = proc.stdout.read(1)
        if char == "":
            break
        buffer += char
        if char == "\n":
            yield buffer.rstrip("\n")
            buffer = ""
    if buffer:
        yield buffer


def run_litmus(
    vm_name: str, settings: Settings, target: Target, log_fh: TextIO | None
) -> TargetResult:
    url = target_base_url(settings, target)
    # litmus selects suites through the $TESTS env var (not positional args).
    prefix: list[str] = (
        ["env", f"TESTS={' '.join(settings.suites)}"] if settings.suites else []
    )
    argv = guest_argv(
        vm_name,
        [*prefix, "litmus", url, target.username, target.password],
    )
    click.secho(f"$ {shlex.join(argv)}", fg="bright_black")
    try:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError as e:
        msg = "command not found: limactl"
        raise ToolError(msg) from e
    result = TargetResult(target=target, suites=[], exit_code=0)
    try:
        for line in _stream_child_lines(proc):
            print(line, flush=True)
            if log_fh is not None:
                log_fh.write(f"{line}\n")
                log_fh.flush()
            _parse_line(result, line)
            # litmus pauses between suites waiting for Return; keep it going.
            if "press Return" in line or "press return" in line:
                assert proc.stdin is not None
                proc.stdin.write("\n")
                proc.stdin.flush()
    finally:
        if proc.stdin is not None:
            try:
                proc.stdin.close()
            except OSError:
                pass
        returncode = proc.wait()
    result.exit_code = returncode
    return result


def _open_run_dir(settings: Settings) -> Path | None:
    if settings.log_dir is None:
        return None
    run_dir = settings.log_dir / f"run-{datetime.now():%Y%m%d-%H%M%S}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _format_count(value: int | None) -> str:
    return "-" if value is None else str(value)


def _print_summary(results: Sequence[TargetResult]) -> None:
    click.secho("\n==== Summary ====", bold=True)
    for result in results:
        status = "PASS" if result.ok else "FAIL"
        color = "green" if result.ok else "red"
        click.secho(f"{result.target.name}: {status}", fg=color, bold=True)
        click.echo(
            f"  exit code: {result.exit_code}, failed checks: {result.total_failed}"
        )
        for suite in result.suites:
            click.echo(
                f"  {suite.name:<12} run {_format_count(suite.run):>4}  "
                f"passed {_format_count(suite.passed):>4}  failed {_format_count(suite.failed):>4}"
            )
    failed_targets = [r for r in results if not r.ok]
    if failed_targets:
        names = ", ".join(r.target.name for r in failed_targets)
        click.secho(
            f"OVERALL: FAIL ({len(failed_targets)}/{len(results)} targets failed: {names})",
            fg="red",
            bold=True,
        )
    else:
        click.secho("OVERALL: PASS", fg="green", bold=True)


@click.group()
def cli() -> None:
    """Run WebDAV litmus compliance tests via a dedicated lima VM."""


@cli.command()
def create() -> None:
    """Create the litmus VM (if missing) and install litmus in it."""
    settings = Settings.load()
    instance = ensure_vm(settings)
    ensure_litmus(instance, settings)


@cli.command()
@click.option("--yes", is_flag=True, help="Skip the confirmation prompt.")
def destroy(yes: bool) -> None:
    """Delete the litmus VM."""
    settings = Settings.load()
    found = vm_instance(settings.vm_name)
    if found is None:
        click.secho(
            f"No lima VM matching {settings.vm_name!r}, nothing to delete.", fg="yellow"
        )
        return
    instance, _state = found
    if not yes:
        click.confirm(f"Delete lima VM {instance!r}?", abort=True)
    result = run_argv(["limactl", "delete", "-f", instance], timeout=VM_TIMEOUT)
    if result.returncode != 0:
        msg = f"limactl delete failed with exit code {result.returncode}"
        raise ToolError(msg)
    click.secho(f"lima VM {instance!r} deleted.", fg="cyan")


@cli.command()
def status() -> None:
    """Show VM state, litmus availability and target reachability."""
    settings = Settings.load()
    found = vm_instance(settings.vm_name)
    if found is None:
        click.echo(f"VM {settings.vm_name}: missing")
        return
    instance, state = found
    click.echo(f"VM {instance}: {state}")
    if state != "Running":
        return
    probe = run_argv(
        guest_argv(instance, ["which", "litmus"]),
        timeout=PROBE_TIMEOUT,
    )
    installed = probe.returncode == 0 and bool(probe.stdout.strip())
    click.echo(f"litmus in VM: {'installed' if installed else 'NOT installed'}")
    checked_urls: set[str] = set()
    for target in settings.targets:
        url = target_base_url(settings, target)
        if url in checked_urls:
            continue
        checked_urls.add(url)
        result = run_argv(
            guest_argv(
                instance,
                ["curl", "-sS", "-o", "/dev/null", "-w", "%{http_code}", url],
            ),
            timeout=PROBE_TIMEOUT,
        )
        body = result.stdout.strip()
        if result.returncode == 0 and re.fullmatch(r"\d{3}", body):
            click.secho(f"{url}: reachable (HTTP {body})", fg="green")
        else:
            detail = body if body else f"curl exit code {result.returncode}"
            click.secho(f"{url}: UNREACHABLE ({detail})", fg="red")


@cli.command()
@click.option(
    "-t",
    "--target",
    "target_names",
    multiple=True,
    metavar="NAME",
    help="Test target (repeatable, default: all configured).",
)
@click.option(
    "-s",
    "--suite",
    "suites",
    multiple=True,
    metavar="NAME",
    help="litmus suite via $TESTS (repeatable, default: all suites).",
)
@click.option(
    "-p", "--port", type=int, default=None, help="Port of the already running server."
)
@click.option("--log-dir", default=None, metavar="PATH", help="Directory for run logs.")
@click.option("--no-log", is_flag=True, help="Do not write run logs.")
@click.option("--no-create", is_flag=True, help="Fail instead of auto-creating the VM.")
def run(
    target_names: tuple[str, ...],
    suites: tuple[str, ...],
    port: int | None,
    log_dir: str | None,
    no_log: bool,
    no_create: bool,
) -> None:
    """Run litmus against all configured targets (server must already run)."""
    settings = Settings.load(
        port=port,
        log_dir=log_dir,
        no_log=no_log,
        target_names=target_names,
        suites=suites,
    )
    instance = ensure_vm(settings, allow_create=not no_create)
    ensure_litmus(instance, settings)
    click.secho(
        f"Expecting the WebDAV server on 0.0.0.0:{settings.server_port}, e.g.:\n"
        f"  python -m asgi_webdav -c examples/config/litmus.toml -H 0.0.0.0",
        fg="yellow",
    )
    # Fail fast on an unreachable server before litmus produces any output.
    probed_urls: set[str] = set()
    for target in settings.targets:
        url = target_base_url(settings, target)
        if url not in probed_urls:
            preflight_from_guest(instance, url)
            probed_urls.add(url)
    run_dir = _open_run_dir(settings)
    click.echo(f"Log dir: {run_dir if run_dir is not None else '(disabled)'}")
    results: list[TargetResult] = []
    try:
        for target in settings.targets:
            click.secho(f"\n==== Target {target.name} ====", bold=True)
            log_fh = None
            if run_dir is not None:
                log_fh = (run_dir / f"{target.name}.log").open("w", encoding="utf-8")
            try:
                results.append(run_litmus(instance, settings, target, log_fh))
            finally:
                if log_fh is not None:
                    log_fh.close()
    finally:
        if results:
            _print_summary(results)
    if not all(result.ok for result in results):
        sys.exit(1)


def main() -> None:
    try:
        cli()
    except ToolError as e:
        click.secho(f"Error: {e}", err=True, fg="red")
        sys.exit(2)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
