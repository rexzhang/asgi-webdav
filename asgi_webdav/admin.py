from asgi_webdav.request import DAVRequest
from asgi_webdav.response import DAVResponse, DAVResponseType


class DAVAdmin:
    async def enter(self, request: DAVRequest):
        if request.path.count <= 2:
            # route /_/admin
            status, data = 200, ""

        elif request.path.parts[2] == "logs":
            # route /_/admin/logs
            status, data = await self.page_logs()

        else:
            status, data = 500, "something wrong"

        await DAVResponse(
            status=status,
            data=data.encode("utf-8"),
            response_type=DAVResponseType.WebPage,
        ).send_in_one_call(request)

    async def page_logs(self) -> (int, str):
        return 200, "this is page /_/admin/logs"
