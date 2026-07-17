from __future__ import annotations

from asgi_webdav.log import get_log_messages
from asgi_webdav.request import DAVRequest
from asgi_webdav.template import TemplateLoader


class WebPage:
    def __init__(self, template_loader: TemplateLoader) -> None:
        self._template_loader = template_loader

    async def enter(self, request: DAVRequest) -> tuple[int, str]:
        if request.path.parts_count <= 2:
            # route
            #   /_
            #   /_/admin
            #   /_/???
            return 200, self.get_index_page()

        # request.path.count > 2
        if not request.user.admin:
            return 403, "Requires administrator privileges"

        if request.path.parts[1] != "admin":
            return 404, ""

        # request.path == "/_/admin/???"
        if request.path.parts[2] == "logging":
            # route /_/admin/logging
            status, data = await self.get_logging_page()

        else:
            status, data = 500, "something wrong"

        return status, data

    def get_index_page(self) -> str:
        return self._template_loader.get_template("admin", "index.html").substitute()

    async def get_logging_page(self) -> tuple[int, str]:
        messages_html = "<br>".join(get_log_messages())
        data = self._template_loader.get_template("admin", "logging.html").substitute(
            messages_html=messages_html
        )
        return 200, data
