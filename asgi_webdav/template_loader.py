from __future__ import annotations

from pathlib import Path
from string import Template

BUNDLED_DIR = Path(__file__).parent / "templates" / "dir_browser"

_TEMPLATE_NAMES = (
    "index.html",
    "row_parent.html",
    "row_directory.html",
    "row_file.html",
)


class DirBrowserTemplateLoader:
    def __init__(self, custom_dir: str | None = None):
        self._custom_dir = Path(custom_dir) if custom_dir else None
        self._templates: dict[str, Template] = {}
        for name in _TEMPLATE_NAMES:
            self._templates[name] = self._load(name)

    def _load(self, name: str) -> Template:
        if self._custom_dir is not None:
            path = self._custom_dir / name
            if path.is_file():
                return Template(path.read_text())
        return Template((BUNDLED_DIR / name).read_text())

    @property
    def index(self) -> Template:
        return self._templates["index.html"]

    @property
    def row_parent(self) -> Template:
        return self._templates["row_parent.html"]

    @property
    def row_directory(self) -> Template:
        return self._templates["row_directory.html"]

    @property
    def row_file(self) -> Template:
        return self._templates["row_file.html"]

    def get_static_root_paths(self) -> list[Path]:
        paths: list[Path] = []
        if self._custom_dir is not None and self._custom_dir.is_dir():
            paths.append(self._custom_dir)
        paths.append(BUNDLED_DIR)
        return paths
