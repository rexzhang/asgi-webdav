from asgi_webdav.exception import NotASGIRequestException
from asgi_webdav.constants import DAVRequest
from asgi_webdav.helpers import (
    send_response_in_one_call,
)
from asgi_webdav.middlewares.http_basic_and_digest_auth import (
    HTTPAuthMiddleware,
)
from asgi_webdav.middlewares.debug import DebugMiddleware
from asgi_webdav.distributor import DAVDistributor


class WebDAV:
    def __init__(self):
        self.dav_distributor = DAVDistributor()

    async def __call__(self, scope, receive, send) -> None:
        try:
            request = DAVRequest(scope, receive, send)

        except NotASGIRequestException as e:
            message = bytes(e.message, encoding='utf-8')
            await send_response_in_one_call(send, 400, message)
            return

        await self.dav_distributor.distribute(request)


app = WebDAV()
# app = HTTPAuthMiddleware(app, 'admin', 'password')
# app = DebugMiddleware(app)
