from __future__ import annotations

import sys
from enum import StrEnum
from logging import getLogger
from pathlib import Path
from typing import Final

from jinja2 import (
    ChoiceLoader,
    Environment,
    FileSystemLoader,
    StrictUndefined,
)
from jinja2 import Template as JinjaTemplate
from jinja2 import TemplateNotFound, TemplateSyntaxError, meta, select_autoescape

from asgi_webdav import __version__

logger = getLogger(__name__)

_BUNDLED_TEMPLATES_DIR = Path(__file__).parent / "templates"

TEMPLATE_MANIFEST: Final[dict[str, tuple[str, ...]]] = {
    "shared": ("base.html",),
    "dir_browser": (
        "index.html",
        "row_parent.html",
        "row_directory.html",
        "row_file.html",
    ),
    "admin": (
        "index.html",
        "logging.html",
    ),
    "error": ("401.html",),
}

_SHARED_TEMPLATE_GROUP = "shared"


class TemplateFailurePolicy(StrEnum):
    FALLBACK = "fallback"
    STOP = "stop"


class TemplateValidationError(Exception):
    """Raised internally when a template or one of its dependencies is invalid."""


def _template_name(page: str, name: str) -> str:
    if page == _SHARED_TEMPLATE_GROUP:
        return name
    return f"{page}/{name}"


def _manifest_template_names() -> tuple[str, ...]:
    return tuple(
        _template_name(page, name)
        for page, names in TEMPLATE_MANIFEST.items()
        for name in names
    )


def _normalize_failure_policy(
    policy: TemplateFailurePolicy | str | None,
) -> TemplateFailurePolicy:
    if isinstance(policy, TemplateFailurePolicy):
        return policy

    if policy is None:
        return TemplateFailurePolicy.FALLBACK

    try:
        return TemplateFailurePolicy(policy.strip().lower())
    except ValueError:
        logger.warning(
            "Unknown template failure policy %r, using %s",
            policy,
            TemplateFailurePolicy.FALLBACK,
        )
        return TemplateFailurePolicy.FALLBACK


class TemplateLoader:
    """Own the bundled/custom template tree and its static asset roots."""

    def __init__(
        self,
        custom_dir: str | Path | None = None,
        failure_policy: TemplateFailurePolicy | str | None = None,
    ) -> None:
        self._failure_policy = _normalize_failure_policy(failure_policy)
        self._custom_dir = self._normalize_custom_dir(custom_dir)
        self._environment = self._build_environment(self._custom_dir)

        self._validate_or_handle_failure()

        if self._custom_dir is not None:
            self._warn_version_mismatch()

    @staticmethod
    def _normalize_custom_dir(custom_dir: str | Path | None) -> Path | None:
        if custom_dir is None:
            return None

        value = str(custom_dir).strip()
        if not value:
            return None

        path = Path(value).expanduser()
        if not path.is_dir():
            logger.warning(
                "Custom template directory does not exist or is not a directory: "
                "%s; using bundled templates",
                path,
            )
            return None

        return path

    @staticmethod
    def _build_environment(custom_dir: Path | None) -> Environment:
        loaders = []
        if custom_dir is not None:
            loaders.append(FileSystemLoader(str(custom_dir)))
        loaders.append(FileSystemLoader(str(_BUNDLED_TEMPLATES_DIR)))

        return Environment(
            loader=ChoiceLoader(loaders),
            autoescape=select_autoescape(["html", "xml"]),
            undefined=StrictUndefined,
            auto_reload=False,
            cache_size=-1,
        )

    @property
    def static_root_paths(self) -> list[Path | str]:
        paths: list[Path | str] = []
        if self._custom_dir is not None:
            paths.append(self._custom_dir)
        paths.append(_BUNDLED_TEMPLATES_DIR)
        return paths

    def get_template(self, page: str, name: str) -> JinjaTemplate:
        template_name = _template_name(page, name)
        try:
            return self._environment.get_template(template_name)
        except TemplateNotFound as error:
            raise FileNotFoundError(f"Template not found: {template_name}") from error

    def _validate_or_handle_failure(self) -> None:
        try:
            self._validate_manifest(self._environment)
        except TemplateValidationError as error:
            self._handle_validation_failure(error)
        except Exception as error:
            self._handle_validation_failure(TemplateValidationError(str(error)))

    def _validate_manifest(self, environment: Environment) -> None:
        validated: set[str] = set()
        for name in _manifest_template_names():
            self._validate_template(environment, name, validated)

    def _validate_template(
        self, environment: Environment, name: str, validated: set[str]
    ) -> None:
        if name in validated:
            return

        validated.add(name)

        loader = environment.loader
        assert loader is not None
        try:
            source, filename, _ = loader.get_source(environment, name)
        except TemplateNotFound as error:
            raise TemplateValidationError(
                f"template '{name}' is missing, or references a missing template: "
                f"{error}"
            ) from error
        except Exception as error:
            raise TemplateValidationError(
                f"template '{name}' could not be read: {error}"
            ) from error

        try:
            ast = environment.parse(source, name=name)
        except TemplateSyntaxError as error:
            location = filename or "unknown"
            raise TemplateValidationError(
                f"template '{name}' ({location}) has a syntax error: {error}"
            ) from error

        for dependency in meta.find_referenced_templates(ast):
            if dependency is None:
                logger.warning(
                    "Template '%s' contains a dynamic extends/include reference "
                    "that cannot be validated at startup",
                    name,
                )
                continue

            self._validate_template(environment, dependency, validated)

    def _handle_validation_failure(self, error: TemplateValidationError) -> None:
        if (
            self._custom_dir is not None
            and self._failure_policy is TemplateFailurePolicy.FALLBACK
        ):
            logger.warning("Custom template validation failed: %s", error)
            logger.warning(
                "Discarding the whole custom template tree in %s and using the "
                "bundled templates only",
                self._custom_dir,
            )

            self._custom_dir = None
            self._environment = self._build_environment(None)
            try:
                self._validate_manifest(self._environment)
            except TemplateValidationError as bundled_error:
                logger.critical("Bundled template validation failed: %s", bundled_error)
                logger.critical("ASGI WebDAV Server has stopped working!")
                sys.exit(1)

            return

        logger.critical("Template validation failed: %s", error)
        logger.critical("ASGI WebDAV Server has stopped working!")
        sys.exit(1)

    def _warn_version_mismatch(self) -> None:
        assert self._custom_dir is not None
        version_file = self._custom_dir / "VERSION"
        if not version_file.is_file():
            return

        try:
            custom_version = version_file.read_text(encoding="utf-8").strip()
        except OSError as error:
            logger.warning(
                "Could not read custom template VERSION file %s: %s",
                version_file,
                error,
            )
            return

        if not custom_version:
            logger.warning("Custom template VERSION file is empty: %s", version_file)
            return

        normalized_version = custom_version.removeprefix("v").removeprefix("V")
        if normalized_version != __version__:
            logger.warning(
                "Custom templates in %s target version %s, but this server is %s; "
                "review your custom templates after upgrading",
                self._custom_dir,
                custom_version,
                __version__,
            )
