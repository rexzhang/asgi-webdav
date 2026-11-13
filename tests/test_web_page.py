from unittest.mock import patch

from asgi_webdav.template import TemplateLoader
from asgi_webdav.web_page import WebPage


def test_get_index_page_uses_template() -> None:
    page = WebPage(TemplateLoader())

    result = page.get_index_page()

    assert "Admin" in result
    assert "/_/admin/logging" in result


async def test_get_logging_page_uses_template() -> None:
    page = WebPage(TemplateLoader())

    with patch("asgi_webdav.web_page.get_log_messages", return_value=["one", "two"]):
        status, result = await page.get_logging_page()

    assert status == 200
    assert "one<br>two" in result
