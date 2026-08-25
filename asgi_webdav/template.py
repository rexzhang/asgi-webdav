from __future__ import annotations

from logging import getLogger
from pathlib import Path
from string import Template

logger = getLogger(__name__)

_BUNDLED_TEMPLATES_DIR = Path(__file__).parent / "templates"


class TemplateLoader:
    def __init__(self, custom_dir: str | None = None) -> None:
        self._custom_dir = Path(custom_dir) if custom_dir else None
        self._builtin_dir = _BUNDLED_TEMPLATES_DIR
        self._cache: dict[str, Template] = {}

    def get_template(self, page: str, name: str) -> Template:
        key = f"{page}/{name}"

        cached = self._cache.get(key)
        if cached is not None:
            return cached

        # try custom dir first
        if self._custom_dir is not None:
            custom_path = self._custom_dir / page / name
            if custom_path.is_file():
                template = Template(custom_path.read_text())
                self._cache[key] = template
                logger.debug(f"Loaded custom template: {custom_path}")
                return template

        # fallback to bundled
        builtin_path = self._builtin_dir / page / name
        if builtin_path.is_file():
            template = Template(builtin_path.read_text())
            self._cache[key] = template
            return template

        raise FileNotFoundError(
            f"Template not found: {page}/{name} "
            f"(searched: {self._custom_dir / page / name if self._custom_dir else 'no custom dir'}, "
            f"{builtin_path})"
        )
