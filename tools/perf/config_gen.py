"""Shared configuration generation for the perf tools.

Single source of truth for the benchmark server config: ``build_config_dict``
returns the plain dict consumed by ``generate_config_from_dict`` (in-process
runs) and ``config_to_toml`` renders the same dict as TOML for the server
subprocess. Keeping both here guarantees the bench / profile / inproc layers
measure identical configurations.

This module must stay importable under every target interpreter (3.14/3.15,
free-threaded builds, inside the lima VM): stdlib + the project only.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

BASIC_USERNAME = "username"
BASIC_PASSWORD = "password"
DIGEST_USERNAME = "username-digest"
DIGEST_PASSWORD = "password"

VARIANTS: tuple[str, ...] = ("base", "quiet", "nocompress")


def digest_ha1(username: str, password: str) -> str:
    """HA1 stored in the config for Digest auth (same format as litmus.toml)."""
    raw = hashlib.md5(f"{username}:ASGI-WebDAV:{password}".encode()).hexdigest()
    return f"<digest>:ASGI-WebDAV:{raw}"


def build_config_dict(
    variant: str = "base",
    *,
    fixtures_fs_uri: str = "memory:///",
    digest: bool = False,
) -> dict[str, Any]:
    """Build the benchmark server config dict (base/quiet/nocompress).

    The fs provider is writable (put/copy workloads need it) — unlike
    examples/config/litmus.toml which is read_only.
    """
    if variant not in VARIANTS:
        msg = f"unknown variant {variant!r}, expected one of {VARIANTS}"
        raise ValueError(msg)

    accounts: list[dict[str, Any]] = [
        {
            "username": BASIC_USERNAME,
            "password": BASIC_PASSWORD,
            "permissions": ["+"],
            "admin": True,
        }
    ]
    if digest:
        accounts.append(
            {
                "username": DIGEST_USERNAME,
                "password": digest_ha1(DIGEST_USERNAME, DIGEST_PASSWORD),
                "permissions": ["+"],
                "admin": False,
            }
        )

    config: dict[str, Any] = {
        "account_mapping": accounts,
        "provider_mapping": [
            # catch-all for OPTIONS / and any unmapped path (read-only)
            {"prefix": "/", "uri": "memory:///", "read_only": True},
            {"prefix": "/fs", "uri": fixtures_fs_uri, "ignore_property_extra": False},
            {"prefix": "/memory", "uri": "memory:///", "ignore_property_extra": False},
        ],
        "logging": {
            "enable": True,
            "level": "CRITICAL" if variant == "quiet" else "INFO",
        },
        "compression": {"enable": variant != "nocompress"},
    }
    if digest:
        config["http_digest_auth"] = {"enable": True}
    return config


def config_to_toml(config: dict[str, Any]) -> str:
    """Render the subset of config used by the benchmark as TOML.

    Hand-rolled emitter: the shapes are fixed (see build_config_dict), the
    stdlib has no toml writer, and dataclass-wizard's TOML support is not
    guaranteed identical across versions.
    """
    lines: list[str] = []
    for account in config["account_mapping"]:
        lines += [
            "[[account_mapping]]",
            f'username = "{account["username"]}"',
            f'password = "{account["password"]}"',
            f'permissions = [{", ".join(json.dumps(p) for p in account["permissions"])}]',
        ]
        if account.get("admin"):
            lines.append("admin = true")
        lines.append("")

    for provider in config["provider_mapping"]:
        lines += [
            "[[provider_mapping]]",
            f'prefix = "{provider["prefix"]}"',
            f'uri = "{provider["uri"]}"',
            "ignore_property_extra = "
            f'{str(provider.get("ignore_property_extra", True)).lower()}',
            "",
        ]
        if provider.get("read_only"):
            lines.insert(-1, "read_only = true")

    if "http_digest_auth" in config:
        lines += ["[http_digest_auth]", "enable = true", ""]

    logging_section = config.get("logging", {})
    if logging_section:
        lines += ["[logging]", f'level = "{logging_section["level"]}"', ""]

    compression = config.get("compression", {})
    if compression:
        lines += ["[compression]", f"enable = {str(compression['enable']).lower()}", ""]

    return "\n".join(lines).rstrip() + "\n"


def fs_uri_for(fixtures_dir: Path) -> str:
    return f"file://{fixtures_dir / 'fs'}"
