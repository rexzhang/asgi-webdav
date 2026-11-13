from click.testing import CliRunner

from asgi_webdav.cli import convert_click_kwargs_to_aep, main


def test_convert_click_kwargs_to_aep_includes_template_options() -> None:
    aep = convert_click_kwargs_to_aep(
        {
            "host": "127.0.0.1",
            "port": 8000,
            "config": None,
            "user": None,
            "root_path": None,
            "dev": False,
            "template_dir": "/custom/templates",
            "template_failure_policy": "stop",
            "logging_display_datetime": True,
        }
    )

    assert aep.template_dir == "/custom/templates"
    assert aep.template_failure_policy == "stop"


def test_convert_click_kwargs_to_aep_without_template_options() -> None:
    aep = convert_click_kwargs_to_aep(
        {
            "host": "127.0.0.1",
            "port": 8000,
            "config": None,
            "user": None,
            "root_path": None,
            "dev": False,
            "logging_display_datetime": True,
        }
    )

    assert aep.template_dir is None
    assert aep.template_failure_policy is None


def test_cli_exposes_template_options_and_removes_litmus() -> None:
    result = CliRunner().invoke(main, ["--help"])

    assert result.exit_code == 0
    assert "--template-dir" in result.output
    assert "--template-failure-policy" in result.output
    assert "--litmus" not in result.output
