import logging.config
from logging import getLogger

from asgi_webdav import __version__
from asgi_webdav.constants import LOGGING_CONFIG
from asgi_webdav.exception import NotASGIRequestException
from asgi_webdav.config import Config
from asgi_webdav.request import DAVRequest
from asgi_webdav.auth import DAVAuth
from asgi_webdav.distributor import DAVDistributor
from asgi_webdav.response import DAVResponse

logger = getLogger(__name__)


class WebDAV:
    def __init__(self, config: Config, in_docker: bool = False):
        LOGGING_CONFIG["loggers"]["asgi_webdav"]["level"] = config.logging_level.value
        if in_docker:
            LOGGING_CONFIG["handlers"]["webdav"]["formatter"] = "webdav_docker"
            LOGGING_CONFIG["handlers"]["uvicorn"]["formatter"] = "uvicorn_docker"

        logging.config.dictConfig(LOGGING_CONFIG)

        logger.info("ASGI WebDAV(v{}) starting...".format(__version__))
        self.auth = DAVAuth(config)
        self.dav_distributor = DAVDistributor(config)

    async def __call__(self, scope, receive, send) -> None:
        try:
            request = DAVRequest(scope, receive, send)

        except NotASGIRequestException as e:
            message = bytes(e.message, encoding="utf-8")
            await DAVResponse(400, message=message).send_in_one_call(send)
            return

        response = self.auth.check_request(request)
        if response:
            # not allow
            await response.send_in_one_call(send)
            return

        await self.dav_distributor.distribute(request)
