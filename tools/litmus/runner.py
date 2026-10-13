"""litmus execution: provisioning, streaming, parsing and reporting."""

from __future__ import annotations

import re
import shlex
import subprocess
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TextIO

import click

from tools.common.error import ToolError
from tools.common.proc import guest_argv, run_argv
from tools.litmus.settings import (
    APT_TIMEOUT,
    PREFLIGHT_HINT,
    PROBE_TIMEOUT,
    Settings,
    Target,
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
