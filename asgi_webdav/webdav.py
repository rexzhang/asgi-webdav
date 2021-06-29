import pathlib
import logging.config
from logging import getLogger


from asgi_middleware_static_file import ASGIMiddlewareStaticFile


from asgi_webdav import __version__
from asgi_webdav.constants import LOGGING_CONFIG, DAVMethod
from asgi_webdav.exception import NotASGIRequestException
from asgi_webdav.config import get_config
from asgi_webdav.request import DAVRequest
from asgi_webdav.auth import DAVAuth
from asgi_webdav.admin import DAVAdmin
from asgi_webdav.distributor import DAVDistributor
from asgi_webdav.response import DAVResponse

logger = getLogger(__name__)


class WebDAV:
    def __init__(self):
        logger.info("ASGI WebDAV Server(v{}) starting...".format(__version__))
        self.dav_auth = DAVAuth()
        self.dev_admin = DAVAdmin()
        self.dav_distributor = DAVDistributor()

    async def __call__(self, scope, receive, send) -> None:
        try:
            request = DAVRequest(scope, receive, send)

        except NotASGIRequestException as e:
            message = bytes(e.message, encoding="utf-8")
            request = DAVRequest({"method": "GET"}, receive, send)
            await DAVResponse(400, data=message).send_in_one_call(request)
            return

        # check user auth
        request.user, message = self.dav_auth.pick_out_user(request)
        if request.user is None:
            logger.debug(request)
            await self.dav_auth.create_response_401(message).send_in_one_call(request)
            return

        # process Admin request
        from icecream import ic

        ic(request.src_path.parts)
        ic(request.user)
        print(request.src_path)
        if (
            request.method == DAVMethod.GET
            and request.user.admin
            and request.src_path.count >= 2
            and request.src_path.parts[0] == "_"
            and request.src_path.parts[1] == "admin"
        ):
            # route /_/admin
            await self.dev_admin.enter(request)
            return

        # process WebDAV method
        await self.dav_distributor.distribute(request)


def get_app(in_docker=False):
    config = get_config()
    LOGGING_CONFIG["loggers"]["asgi_webdav"]["level"] = config.logging_level.value
    if in_docker:
        LOGGING_CONFIG["handlers"]["webdav"]["formatter"] = "webdav_docker"
        LOGGING_CONFIG["handlers"]["uvicorn"]["formatter"] = "uvicorn_docker"

    logging.config.dictConfig(LOGGING_CONFIG)

    app = WebDAV()

    # route /_/static
    app = ASGIMiddlewareStaticFile(
        app=app,
        static_url="_/static",
        static_root_paths=[pathlib.Path(__file__).parent.joinpath("static")],
    )

    return app
