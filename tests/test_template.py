import logging
from pathlib import Path
from typing import Any

import pytest
from jinja2 import Environment, FileSystemLoader, meta
from pytest_mock import MockerFixture

from asgi_webdav import __version__
from asgi_webdav.template import (
    _BUNDLED_TEMPLATES_DIR,
    TEMPLATE_MANIFEST,
    InvalidTemplateFailurePolicyError,
    TemplateFailurePolicy,
    TemplateLoader,
)


def template_names_from_manifest() -> list[str]:
    names = []
    for page, page_templates in TEMPLATE_MANIFEST.items():
        for name in page_templates:
            names.append(name if page == "shared" else f"{page}/{name}")
    return names


def make_custom_template(root: Path, template_name: str, content: str) -> Path:
    path = root / template_name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def render_template(loader: TemplateLoader, page: str, name: str) -> str:
    return loader.get_template(page, name).render(
        path="/",
        parent=None,
        items=[],
        version="test",
        current_time="now",
        message="test",
        messages=[],
    )


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


def test_partial_customisation_keeps_bundled_templates(tmp_path: Path) -> None:
    make_custom_template(tmp_path, "error/401.html", "CUSTOM 401 {{ message }}")

    loader = TemplateLoader(str(tmp_path))

    assert (
        loader.get_template("error", "401.html").render(message="denied")
        == "CUSTOM 401 denied"
    )
    assert "Index of /" in render_template(loader, "dir_browser", "index.html")


def test_missing_template_raises_file_not_found() -> None:
    loader = TemplateLoader()

    with pytest.raises(FileNotFoundError):
        loader.get_template("missing", "page.html")


@pytest.mark.parametrize("custom_dir", [None, "", "   ", "\t\n"])
def test_empty_custom_dir_never_uses_working_directory(
    custom_dir: str | None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Path("") == Path("."), so an un-normalized empty value would expose the
    # whole working directory through /_/static/.
    make_custom_template(tmp_path, "dir_browser/index.html", "LEAKED {{ path }}")
    monkeypatch.chdir(tmp_path)

    loader = TemplateLoader(custom_dir)

    assert loader.static_root_paths == [_BUNDLED_TEMPLATES_DIR]
    assert Path.cwd() not in loader.static_root_paths
    assert "LEAKED" not in render_template(loader, "dir_browser", "index.html")


def test_valid_custom_dir_is_used_for_templates_and_static_assets(
    tmp_path: Path,
) -> None:
    make_custom_template(tmp_path, "dir_browser/index.html", "CUSTOM {{ path }}")

    loader = TemplateLoader(str(tmp_path))

    assert loader.static_root_paths == [tmp_path, _BUNDLED_TEMPLATES_DIR]
    assert loader.get_template("dir_browser", "index.html").render(path="/") == (
        "CUSTOM /"
    )


def test_nonexistent_custom_dir_uses_bundled_templates(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    missing = tmp_path / "missing"

    with caplog.at_level(logging.WARNING):
        loader = TemplateLoader(str(missing))

    assert loader.static_root_paths == [_BUNDLED_TEMPLATES_DIR]
    assert "does not exist" in caplog.text
    assert "Index of /" in render_template(loader, "dir_browser", "index.html")


def test_invalid_custom_template_falls_back_to_complete_bundled_tree(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    make_custom_template(tmp_path, "dir_browser/index.html", "{% if")
    make_custom_template(tmp_path, "error/401.html", "CUSTOM 401")

    with caplog.at_level(logging.WARNING):
        loader = TemplateLoader(str(tmp_path))

    assert "Custom template validation failed" in caplog.text
    assert "Discarding the whole custom template tree" in caplog.text

    # the entire custom tree is discarded, not just the broken file
    assert loader.static_root_paths == [_BUNDLED_TEMPLATES_DIR]
    assert "CUSTOM 401" not in render_template(loader, "error", "401.html")
    assert "Index of /" in render_template(loader, "dir_browser", "index.html")


def test_stop_policy_exits_with_status_one(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    make_custom_template(tmp_path, "dir_browser/index.html", "{% if")

    with caplog.at_level(logging.CRITICAL):
        with pytest.raises(SystemExit) as exc_info:
            TemplateLoader(str(tmp_path), TemplateFailurePolicy.STOP)

    assert exc_info.value.code == 1
    assert "Template validation failed" in caplog.text


@pytest.mark.parametrize(
    "source",
    [
        '{% extends "dir_browser/broken.html" %}',
        '{% include "dir_browser/broken.html" %}',
        '{% include "dir_browser/broken.html" ignore missing %}',
        '{% if false %}{% extends "dir_browser/broken.html" %}{% endif %}',
    ],
)
def test_validation_walks_extends_and_include_dependencies(
    source: str, tmp_path: Path
) -> None:
    make_custom_template(tmp_path, "dir_browser/index.html", source)
    make_custom_template(tmp_path, "dir_browser/broken.html", "{% if")

    with pytest.raises(SystemExit) as exc_info:
        TemplateLoader(str(tmp_path), TemplateFailurePolicy.STOP)

    assert exc_info.value.code == 1


@pytest.mark.parametrize(
    "source",
    [
        '{% include "partials/missing.html" ignore missing %}',
        '{% if false %}{% extends "partials/missing.html" %}{% endif %}',
        '{% include "partials/missing.html" %}',
    ],
)
def test_missing_dependency_is_a_warning_not_a_failure(
    source: str, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    make_custom_template(tmp_path, "dir_browser/index.html", source)

    with caplog.at_level(logging.WARNING):
        loader = TemplateLoader(str(tmp_path), TemplateFailurePolicy.STOP)

    assert "partials/missing.html" in caplog.text
    assert loader.static_root_paths == [tmp_path, _BUNDLED_TEMPLATES_DIR]


def test_ignore_missing_include_renders_without_the_target(tmp_path: Path) -> None:
    make_custom_template(
        tmp_path,
        "dir_browser/index.html",
        'A{% include "partials/missing.html" ignore missing %}B',
    )

    loader = TemplateLoader(str(tmp_path), TemplateFailurePolicy.STOP)

    assert render_template(loader, "dir_browser", "index.html") == "AB"


def test_valid_extends_and_include_dependencies_are_accepted(
    tmp_path: Path,
) -> None:
    make_custom_template(
        tmp_path,
        "dir_browser/index.html",
        '{% extends "base.html" %}{% include "error/401.html" %}',
    )

    loader = TemplateLoader(str(tmp_path), TemplateFailurePolicy.STOP)

    assert loader.static_root_paths == [tmp_path, _BUNDLED_TEMPLATES_DIR]


def test_template_cache_is_reused() -> None:
    loader = TemplateLoader()

    first = loader.get_template("admin", "index.html")
    second = loader.get_template("admin", "index.html")

    assert first is second


def test_manifest_entries_exist_in_bundled_tree() -> None:
    for template_name in template_names_from_manifest():
        assert (_BUNDLED_TEMPLATES_DIR / template_name).is_file(), template_name


def test_every_bundled_html_template_is_registered_or_reachable() -> None:
    environment = Environment(
        loader=FileSystemLoader(str(_BUNDLED_TEMPLATES_DIR)),
    )
    loader = environment.loader
    assert loader is not None

    reachable = set(template_names_from_manifest())
    pending = list(reachable)
    while pending:
        template_name = pending.pop()
        source, _, _ = loader.get_source(environment, template_name)
        ast = environment.parse(source, name=template_name)
        for dependency in meta.find_referenced_templates(ast):
            if dependency is not None and dependency not in reachable:
                reachable.add(dependency)
                pending.append(dependency)

    bundled_templates = {
        path.relative_to(_BUNDLED_TEMPLATES_DIR).as_posix()
        for path in _BUNDLED_TEMPLATES_DIR.rglob("*.html")
    }
    assert bundled_templates <= reachable


def test_matching_version_file_does_not_warn(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / "VERSION").write_text(__version__, encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        TemplateLoader(str(tmp_path))

    assert "target version" not in caplog.text


def test_different_version_file_warns(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / "VERSION").write_text("0.0.0", encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        loader = TemplateLoader(str(tmp_path))

    assert "target version 0.0.0" in caplog.text
    assert loader.static_root_paths == [tmp_path, _BUNDLED_TEMPLATES_DIR]


def test_policy_string_is_normalized(tmp_path: Path) -> None:
    make_custom_template(tmp_path, "dir_browser/index.html", "{% if")

    with pytest.raises(SystemExit):
        TemplateLoader(str(tmp_path), " STOP ")


@pytest.mark.parametrize("policy", ["bogus", "", "stpo", "fallback stop"])
def test_unknown_policy_is_rejected(tmp_path: Path, policy: str) -> None:
    make_custom_template(tmp_path, "dir_browser/index.html", "{% if")

    with pytest.raises(InvalidTemplateFailurePolicyError, match="'fallback', 'stop'"):
        TemplateLoader(str(tmp_path), policy)


def test_unexpected_validation_error_is_handled_like_template_failure(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    mocker.patch.object(
        TemplateLoader, "_validate_manifest", side_effect=RuntimeError("boom")
    )

    with caplog.at_level(logging.CRITICAL):
        with pytest.raises(SystemExit) as exc_info:
            TemplateLoader()

    assert exc_info.value.code == 1
    assert "boom" in caplog.text


def test_unreadable_custom_template_fails_validation(
    tmp_path: Path,
    mocker: MockerFixture,
    caplog: pytest.LogCaptureFixture,
) -> None:
    make_custom_template(tmp_path, "dir_browser/index.html", "CUSTOM")
    original_get_source = FileSystemLoader.get_source

    def get_source(
        self: FileSystemLoader, environment: Environment, template: str
    ) -> Any:
        if (
            Path(self.searchpath[0]) == tmp_path
            and template == "dir_browser/index.html"
        ):
            raise OSError("permission denied")
        return original_get_source(self, environment, template)

    mocker.patch.object(FileSystemLoader, "get_source", get_source)

    with caplog.at_level(logging.WARNING):
        loader = TemplateLoader(str(tmp_path))

    assert "could not be read" in caplog.text
    assert loader.static_root_paths == [_BUNDLED_TEMPLATES_DIR]


def test_dynamic_extends_reference_is_warned_not_failed(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    make_custom_template(
        tmp_path, "dir_browser/index.html", "{% include layout_name %}"
    )

    with caplog.at_level(logging.WARNING):
        loader = TemplateLoader(str(tmp_path), TemplateFailurePolicy.STOP)

    assert "dynamic extends/include reference" in caplog.text
    assert loader.static_root_paths == [tmp_path, _BUNDLED_TEMPLATES_DIR]


def test_broken_bundled_tree_is_fatal(
    tmp_path: Path,
    mocker: MockerFixture,
    caplog: pytest.LogCaptureFixture,
) -> None:
    bundled = tmp_path / "bundled"
    make_custom_template(bundled, "base.html", "{% if")
    mocker.patch("asgi_webdav.template._BUNDLED_TEMPLATES_DIR", bundled)
    custom = tmp_path / "custom"
    make_custom_template(custom, "dir_browser/index.html", "{% if")

    with caplog.at_level(logging.CRITICAL):
        with pytest.raises(SystemExit) as exc_info:
            TemplateLoader(str(custom))

    assert exc_info.value.code == 1
    assert "Bundled template validation failed" in caplog.text


def test_unreadable_version_file_warns(
    tmp_path: Path,
    mocker: MockerFixture,
    caplog: pytest.LogCaptureFixture,
) -> None:
    (tmp_path / "VERSION").write_text(__version__, encoding="utf-8")
    original_read_text = Path.read_text

    def read_text(self: Path, *args: Any, **kwargs: Any) -> str:
        if self.name == "VERSION":
            raise OSError("permission denied")
        return original_read_text(self, *args, **kwargs)

    mocker.patch.object(Path, "read_text", read_text)

    with caplog.at_level(logging.WARNING):
        loader = TemplateLoader(str(tmp_path))

    assert "Could not read custom template VERSION file" in caplog.text
    assert loader.static_root_paths == [tmp_path, _BUNDLED_TEMPLATES_DIR]


def test_empty_version_file_warns(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / "VERSION").write_text("  \n", encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        TemplateLoader(str(tmp_path))

    assert "VERSION file is empty" in caplog.text


def test_missing_version_file_is_allowed(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        loader = TemplateLoader(str(tmp_path))

    assert loader.static_root_paths == [tmp_path, _BUNDLED_TEMPLATES_DIR]
    assert "VERSION" not in caplog.text
