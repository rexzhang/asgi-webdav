"""lima VM plumbing shared by the developer tools.

``ensure_vm`` parameterizes the two historical behaviors: ``interactive=True``
reproduces the litmus tool (progress messages, passthrough output, ToolError
on nonzero create/start exit codes); the default quiet mode reproduces the
perf tool (silent, failures surfaced later by the caller).
"""

from __future__ import annotations

import json
import shlex
from typing import Any

import click

from tools.common.error import ToolError
from tools.common.proc import run_argv


def vm_instance(vm_name: str, *, timeout: float) -> tuple[str, str] | None:
    """Return (instance name, status) for the exact instance, if it exists."""
    result = run_argv(["limactl", "list", "--json"], timeout=timeout)
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


def ensure_vm(
    vm_name: str,
    *,
    template: str,
    disk_gib: int,
    create_timeout: float,
    start_timeout: float,
    allow_create: bool = True,
    interactive: bool = False,
    probe_timeout: float = 30.0,
) -> str:
    found = vm_instance(vm_name, timeout=probe_timeout)
    if found is None:
        create_argv = [
            "limactl",
            "create",
            "--plain",
            "--disk",
            str(disk_gib),
            "--name",
            vm_name,
            template,
        ]
        if not allow_create:
            msg = (
                f"lima VM {vm_name!r} does not exist and creation is disabled, "
                f"create it with: {shlex.join(create_argv)}"
            )
            raise ToolError(msg)
        if interactive:
            click.secho(
                f"Creating lima VM {vm_name!r} from {template!r} ...", fg="cyan"
            )
        result = run_argv(create_argv, timeout=create_timeout, passthrough=interactive)
        if interactive and result.returncode != 0:
            msg = f"limactl create failed with exit code {result.returncode}"
            raise ToolError(msg)
        found = vm_instance(vm_name, timeout=probe_timeout)
        if interactive and found is None:
            msg = f"limactl create finished but no instance for {vm_name!r} was found"
            raise ToolError(msg)
        if found is None:
            msg = "VM creation failed"
            raise ToolError(msg)
    instance, status = found
    if status != "Running":
        if interactive:
            click.secho(f"Starting lima VM {instance!r} ...", fg="cyan")
        result = run_argv(
            ["limactl", "start", instance],
            timeout=start_timeout,
            passthrough=interactive,
        )
        if interactive and result.returncode != 0:
            msg = f"limactl start failed with exit code {result.returncode}"
            raise ToolError(msg)
    if interactive:
        click.secho(f"lima VM {instance!r} is ready.", fg="cyan")
    return instance
