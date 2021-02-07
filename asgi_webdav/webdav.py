from asgi_webdav.exception import NotASGIRequestException
from asgi_webdav.helpers import (
    send_response_in_one_call,
)
from asgi_webdav.request import DAVRequest
from asgi_webdav.distributor import DAVDistributor


class WebDAV:
    def __init__(self, dist_map: dict[str, str]):
        self.dav_distributor = DAVDistributor(dist_map)

    async def __call__(self, scope, receive, send) -> None:
        try:
            request = DAVRequest(scope, receive, send)

        except NotASGIRequestException as e:
            message = bytes(e.message, encoding='utf-8')
            await send_response_in_one_call(send, 400, message)
            return

        await self.dav_distributor.distribute(request)
