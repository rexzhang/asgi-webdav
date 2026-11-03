from pathlib import Path

import pytest

from asgi_webdav.template import TemplateLoader


def test_bundled_template_renders_with_html_escaping() -> None:
    loader = TemplateLoader()

    rendered = loader.get_template("dir_browser", "row_file.html").render(
        item={
            "href": "/file.txt",
            "name": "<file>",
            "type": "text/plain",
            "size": 4,
            "modified": "today",
        }
    )

    assert "&lt;file&gt;" in rendered


def test_custom_template_falls_back_per_file(tmp_path: Path) -> None:
    custom_dir = tmp_path / "dir_browser"
    custom_dir.mkdir()
    (custom_dir / "index.html").write_text("CUSTOM {{ path }}")

    loader = TemplateLoader(str(tmp_path))

    assert loader.get_template("dir_browser", "index.html").render(path="/") == (
        "CUSTOM /"
    )
    assert loader.get_template("dir_browser", "row_file.html")


def test_missing_template_raises_file_not_found() -> None:
    loader = TemplateLoader()

    with pytest.raises(FileNotFoundError):
        loader.get_template("missing", "page.html")
