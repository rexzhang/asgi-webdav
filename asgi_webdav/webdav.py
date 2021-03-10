import logging.config

from asgi_webdav.constants import (
    LOGGING_CONFIG,
)
from asgi_webdav.config import Config
from asgi_webdav.exception import NotASGIRequestException
from asgi_webdav.request import DAVRequest
from asgi_webdav.distributor import DAVDistributor
from asgi_webdav.response import DAVResponse


class WebDAV:
    def __init__(self, config: Config):
        LOGGING_CONFIG['loggers']['asgi_webdav'][
            'level'] = config.logging_level.value
        logging.config.dictConfig(LOGGING_CONFIG)

        self.dav_distributor = DAVDistributor(config)

    async def __call__(self, scope, receive, send) -> None:
        try:
            request = DAVRequest(scope, receive, send)

        except NotASGIRequestException as e:
            message = bytes(e.message, encoding='utf-8')
            await DAVResponse(400, message=message).send_in_one_call(send)
            return

        await self.dav_distributor.distribute(request)
