import logging.config

from asgi_webdav.exception import NotASGIRequestException
from asgi_webdav.request import DAVRequest
from asgi_webdav.distributor import DAVDistributor
from asgi_webdav.constants import (
    LOGGING_CONFIG,
    DAVResponse,
)


class WebDAV:
    def __init__(self, dist_map: dict[str, str]):
        logging.config.dictConfig(LOGGING_CONFIG)
        self.dav_distributor = DAVDistributor(dist_map)

    async def __call__(self, scope, receive, send) -> None:
        try:
            request = DAVRequest(scope, receive, send)

        except NotASGIRequestException as e:
            message = bytes(e.message, encoding='utf-8')
            await DAVResponse(400, message).send_in_one_call(send)
            return

        await self.dav_distributor.distribute(request)
