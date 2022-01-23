from asgi_webdav.request import DAVRequest
from asgi_webdav.log import get_log_messages


class WebPage:
    async def enter(self, request: DAVRequest):
        if request.path.count <= 2:
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
        return '<a href="/_/admin/logging">Logging page</a>'

    async def get_logging_page(self) -> (int, str):
        # return 200, "this is page /_/admin/logs"
        data = str()
        for message in get_log_messages():
            data += message + "<br>"
        return 200, data
