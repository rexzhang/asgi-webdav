from __future__ import annotations

from pathlib import Path
from typing import Final

from jinja2 import (
    ChoiceLoader,
    Environment,
    FileSystemLoader,
    StrictUndefined,
)
from jinja2 import Template as JinjaTemplate
from jinja2 import TemplateNotFound, meta, select_autoescape

_BUNDLED_TEMPLATES_DIR = Path(__file__).parent / "templates"
_KNOWN_TEMPLATES: Final = (
    "base.html",
    "dir_browser/index.html",
    "dir_browser/row_parent.html",
    "dir_browser/row_directory.html",
    "dir_browser/row_file.html",
    "admin/index.html",
    "admin/logging.html",
    "error/401.html",
)


class TemplateLoader:
    def __init__(self, custom_dir: str | None = None) -> None:
        loaders = []
        if custom_dir:
            loaders.append(FileSystemLoader(custom_dir))
        loaders.append(FileSystemLoader(_BUNDLED_TEMPLATES_DIR))

        self._environment = Environment(
            loader=ChoiceLoader(loaders),
            autoescape=select_autoescape(["html", "xml"]),
            undefined=StrictUndefined,
            auto_reload=False,
            cache_size=-1,
        )
        self._validate_known_templates()

    def _validate_known_templates(self) -> None:
        validated: set[str] = set()

        for name in _KNOWN_TEMPLATES:
            self._validate_template(name, validated)

    def _validate_template(self, name: str, validated: set[str]) -> None:
        if name in validated:
            return

        self._environment.get_template(name)
        loader = self._environment.loader
        assert loader is not None
        source, _, _ = loader.get_source(self._environment, name)
        ast = self._environment.parse(source)
        validated.add(name)
        for dependency in meta.find_referenced_templates(ast):
            if dependency is not None:
                self._validate_template(dependency, validated)

    def get_template(self, page: str, name: str) -> JinjaTemplate:
        template_name = f"{page}/{name}"
        try:
            return self._environment.get_template(template_name)
        except TemplateNotFound as error:
            raise FileNotFoundError(f"Template not found: {template_name}") from error
