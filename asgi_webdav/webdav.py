import logging.config
from logging import getLogger

from asgi_webdav import __version__
from asgi_webdav.constants import LOGGING_CONFIG
from asgi_webdav.exception import NotASGIRequestException
from asgi_webdav.config import get_config
from asgi_webdav.request import DAVRequest
from asgi_webdav.auth import DAVAuth
from asgi_webdav.distributor import DAVDistributor
from asgi_webdav.response import DAVResponse

logger = getLogger(__name__)


class WebDAV:
    def __init__(self, in_docker: bool = False):
        config = get_config()
        LOGGING_CONFIG["loggers"]["asgi_webdav"]["level"] = config.logging_level.value
        if in_docker:
            LOGGING_CONFIG["handlers"]["webdav"]["formatter"] = "webdav_docker"
            LOGGING_CONFIG["handlers"]["uvicorn"]["formatter"] = "uvicorn_docker"

        logging.config.dictConfig(LOGGING_CONFIG)

        logger.info("ASGI WebDAV(v{}) starting...".format(__version__))
        self.dav_distributor = DAVDistributor()
        self.dav_auth = DAVAuth()

    async def __call__(self, scope, receive, send) -> None:
        try:
            request = DAVRequest(scope, receive, send)

        except NotASGIRequestException as e:
            message = bytes(e.message, encoding="utf-8")
            request = DAVRequest({"method": "GET"}, receive, send)
            await DAVResponse(400, data=message).send_in_one_call(request)
            return

        # check permission
        request.user, message = self.dav_auth.pick_out_user(request)
        if request.user is None:
            logger.debug(request)
            await self.dav_auth.create_response_401(message).send_in_one_call(request)
            return

        await self.dav_distributor.distribute(request)
