"""Settings (TOOLS_PERF_* env contract) and perf-only env helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from tools.common.env import REPO_ROOT, env_float, env_int, env_int_list, env_str


def _env(key: str, default: str = "") -> str:
    # call sites pass FULL keys (e.g. "TOOLS_PERF_DURATION") — an empty
    # prefix keeps common.env from doubling it
    return env_str("", key, default)


def _env_int(key: str, default: int) -> int:
    return env_int("", key, default)


def _env_float(key: str, default: float) -> float:
    return env_float("", key, default)


def _env_int_list(key: str, default: str) -> tuple[int, ...]:
    return env_int_list("", key, default)


PROBE_TIMEOUT = 20.0
# shared with the litmus tool: one VM serves all developer tools
DEFAULT_VM_NAME = "asgi-webdav-tools-d13"
DEFAULT_VM_TEMPLATE = "template:debian"
DEFAULT_VM_DISK = 40


def _resolve_dir(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else REPO_ROOT / path


@dataclass(frozen=True)
class Settings:
    python_314: str
    python_315: str
    python_315t: str
    loadgen: str
    duration: float
    repeats: int
    warmup: int
    concurrencies: tuple[int, ...]
    cooldown: float
    fixtures_dir: Path
    log_dir: Path
    sampling_rate: str
    profile_duration: float
    vm_name: str
    vm_template: str
    vm_disk: int
    apt_mirror: str

    @classmethod
    def load(cls) -> Settings:
        return cls(
            python_314=_env("TOOLS_PERF_PYTHON_314", ".venv314/bin/python"),
            python_315=_env("TOOLS_PERF_PYTHON_315", ".venv/bin/python"),
            python_315t=_env("TOOLS_PERF_PYTHON_315T", ""),
            loadgen=_env("TOOLS_PERF_LOADGEN", "auto"),
            duration=_env_float("TOOLS_PERF_DURATION", 10.0),
            repeats=_env_int("TOOLS_PERF_REPEATS", 5),
            warmup=_env_int("TOOLS_PERF_WARMUP", 1),
            concurrencies=_env_int_list("TOOLS_PERF_CONCURRENCIES", "1,4,16"),
            cooldown=_env_float("TOOLS_PERF_COOLDOWN", 2.0),
            fixtures_dir=_resolve_dir(
                _env("TOOLS_PERF_FIXTURES_DIR", "output/perf/fixtures")
            ),
            log_dir=_resolve_dir(_env("TOOLS_PERF_LOG_DIR", "output/perf")),
            sampling_rate=_env("TOOLS_PERF_SAMPLING_RATE", "10khz"),
            profile_duration=_env_float("TOOLS_PERF_PROFILE_DURATION", 20.0),
            vm_name=_env("TOOLS_PERF_VM_NAME", DEFAULT_VM_NAME),
            vm_template=_env("TOOLS_PERF_VM_TEMPLATE", DEFAULT_VM_TEMPLATE),
            vm_disk=_env_int("TOOLS_PERF_VM_DISK", DEFAULT_VM_DISK),
            apt_mirror=_env("TOOLS_PERF_APT_MIRROR", ""),
        )


# ---------------------------------------------------------------------------
# subprocess helpers


def scrub_child_env() -> dict[str, str]:
    """Drop env vars that would leak into the app config (EnvWizard reads
    .env by cwd AND the process env; see tests/test_server.py clean_env)."""
    return {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("WEBDAV_") and not k.startswith("SENTRY_")
    }
