import sentry_sdk
from sentry_sdk.integrations.asgi import SentryAsgiMiddleware

from asgi_webdav.helpers import (
    parser_asgi_request,
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
        request, msg = parser_asgi_request(scope, receive, send)
        if request is None:
            await send_response_in_one_call(send, 400, msg)
            return

        await self.dav_distributor.distribute(request)


app = WebDAV()
# app = HTTPAuthMiddleware(app, 'admin', 'password')
# app = DebugMiddleware(app)
