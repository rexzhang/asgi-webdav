from asgi_webdav.cli import convert_click_kwargs_to_aep


def test_convert_click_kwargs_to_aep_includes_template_dir() -> None:
    aep = convert_click_kwargs_to_aep(
        {
            "host": "127.0.0.1",
            "port": 8000,
            "config": None,
            "user": None,
            "root_path": None,
            "dev": False,
            "template_dir": "/custom/templates",
            "logging_display_datetime": True,
        }
    )

    assert aep.template_dir == "/custom/templates"
