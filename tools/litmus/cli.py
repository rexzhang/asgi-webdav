"""Click CLI for the litmus tool (python -m tools.litmus)."""

from __future__ import annotations

import re
import sys

import click

from tools.common.error import ToolError
from tools.common.lima import ensure_vm, vm_instance
from tools.common.proc import guest_argv, run_argv
from tools.litmus.runner import (
    TargetResult,
    _open_run_dir,
    _print_summary,
    ensure_litmus,
    preflight_from_guest,
    run_litmus,
    target_base_url,
)
from tools.litmus.settings import (
    PROBE_TIMEOUT,
    VM_TIMEOUT,
    Settings,
)


@click.group()
def cli() -> None:
    """Run WebDAV litmus compliance tests via a dedicated lima VM."""


@cli.command()
def create() -> None:
    """Create the litmus VM (if missing) and install litmus in it."""
    settings = Settings.load()
    instance = ensure_vm(
        settings.vm_name,
        template=settings.vm_template,
        disk_gib=settings.vm_disk,
        create_timeout=VM_TIMEOUT,
        start_timeout=VM_TIMEOUT,
        interactive=True,
        probe_timeout=PROBE_TIMEOUT,
    )
    ensure_litmus(instance, settings)


@cli.command()
@click.option("--yes", is_flag=True, help="Skip the confirmation prompt.")
def destroy(yes: bool) -> None:
    """Delete the litmus VM."""
    settings = Settings.load()
    found = vm_instance(settings.vm_name, timeout=PROBE_TIMEOUT)
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
    found = vm_instance(settings.vm_name, timeout=PROBE_TIMEOUT)
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
    instance = ensure_vm(
        settings.vm_name,
        template=settings.vm_template,
        disk_gib=settings.vm_disk,
        create_timeout=VM_TIMEOUT,
        start_timeout=VM_TIMEOUT,
        allow_create=not no_create,
        interactive=True,
        probe_timeout=PROBE_TIMEOUT,
    )
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
