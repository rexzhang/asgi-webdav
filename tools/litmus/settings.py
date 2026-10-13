"""Targets and the TOOLS_LITMUS_* settings contract."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from tools.common.env import REPO_ROOT, env_int, env_list, env_str
from tools.common.error import ToolError

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


def _env(key: str, default: str = "") -> str:
    return env_str("", key, default)


def _env_int(key: str, default: int) -> int:
    return env_int("", key, default)


def _env_list(key: str) -> tuple[str, ...]:
    return env_list("", key)


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
