import logging.config
import pathlib
import sys
from logging import getLogger

from asgi_middleware_static_file import ASGIMiddlewareStaticFile

from asgi_webdav import __name__ as app_name
from asgi_webdav import __version__
from asgi_webdav.auth import DAVAuth
from asgi_webdav.config import (
    Config,
    get_config,
    init_config_from_file,
    init_config_from_obj,
)
from asgi_webdav.constants import AppEntryParameters, ASGIScope, DAVMethod, DevMode
from asgi_webdav.exception import NotASGIRequestException, ProviderInitException
from asgi_webdav.log import get_dav_logging_config
from asgi_webdav.middleware.cors import ASGIMiddlewareCORS
from asgi_webdav.request import DAVRequest
from asgi_webdav.response import DAVResponse
from asgi_webdav.web_dav import WebDAV
from asgi_webdav.web_page import WebPage

logger = getLogger(__name__)


_service_abnormal_exit_message = "ASGI WebDAV Server has stopped working!"


class Server:
    def __init__(self, config: Config):
        logger.info(f"ASGI WebDAV Server(v{__version__}) starting...")
        self.dav_auth = DAVAuth(config)
        try:
            self.web_dav = WebDAV(config)

        except ProviderInitException as e:
            logger.critical(e)
            logger.info(_service_abnormal_exit_message)
            sys.exit(1)

        self.web_page = WebPage()

    async def __call__(self, scope: ASGIScope, receive, send) -> None:
        try:
            request, response = await self.handle(scope, receive, send)
        except NotASGIRequestException as e:
            message = bytes(e.message, encoding="utf-8")
            request = DAVRequest(ASGIScope({"method": "GET"}), receive, send)
            await DAVResponse(400, content=message).send_in_one_call(request)
            return

        logger.info(
            '%s - "%s %s" %d %s - %s',
            request.client_ip_address,
            request.method,
            request.path,
            response.status,
            request.authorization_method,  # Basic/Digest
            request.client_user_agent,
        )
        logger.debug(request.headers)
        await response.send_in_one_call(request)

    async def handle(
        self, scope: ASGIScope, receive, send
    ) -> (DAVRequest, DAVResponse):
        request = DAVRequest(scope, receive, send)

        # check user auth
        request.user, message = await self.dav_auth.pick_out_user(request)
        if request.user is None:
            logger.debug(request)
            return request, self.dav_auth.create_response_401(request, message)

        # process Admin request
        if (
            request.method == DAVMethod.GET
            and request.src_path.count >= 1
            and request.src_path.parts[0] == "_"
        ):
            # route /_
            status, data = await self.web_page.enter(request)
            return request, DAVResponse(
                status=status,
                content=data.encode("utf-8"),
            )

        # process WebDAV request
        try:
            response = await self.web_dav.distribute(request)

        except ProviderInitException as e:
            logger.critical(e)
            logger.info(_service_abnormal_exit_message)
            sys.exit(1)

        logger.debug(response)
        return request, response


def get_asgi_app(aep: AppEntryParameters, config_obj: dict | None = None):
    """create ASGI app"""
    logging.config.dictConfig(get_dav_logging_config())

    # init config
    if aep.config_file is not None:
        init_config_from_file(aep.config_file)
    if config_obj is not None:
        init_config_from_obj(config_obj)

    config = get_config()
    config.update_from_app_args_and_env_and_default_value(aep=aep)

    # TODO LOGGING_CONFIG
    logging.config.dictConfig(
        get_dav_logging_config(
            level=config.logging_level.name,
            display_datetime=aep.logging_display_datetime,
            use_colors=aep.logging_use_colors,
        )
    )
    logger.debug(config.dict())

    # create ASGI app
    app = Server(config)

    # route /_/static
    app = ASGIMiddlewareStaticFile(
        app=app,
        static_url="_/static",
        static_root_paths=[pathlib.Path(__file__).parent.joinpath("static")],
    )

    # CORS
    if config.cors.enable:
        app = ASGIMiddlewareCORS(
            app=app,
            allow_url_regex=config.cors.allow_url_regex,
            allow_origins=config.cors.allow_origins,
            allow_origin_regex=config.cors.allow_origin_regex,
            allow_methods=config.cors.allow_methods,
            allow_headers=config.cors.allow_headers,
            allow_credentials=config.cors.allow_credentials,
            expose_headers=config.cors.expose_headers,
            preflight_max_age=config.cors.preflight_max_age,
        )

    # config sentry
    if config.sentry_dsn:
        try:
            import sentry_sdk
            from sentry_sdk.integrations.asgi import SentryAsgiMiddleware

            sentry_sdk.init(
                dsn=config.sentry_dsn,
                release=f"{app_name}@{__version__}",
            )
            app = SentryAsgiMiddleware(app)

        except ImportError as e:
            logger.warning(e)

    logger.info(
        "ASGI WebDAV Server running on http://{}:{} (Press CTRL+C to quit)".format(
            aep.bind_host if aep.bind_host is not None else "?",
            aep.bind_port if aep.bind_port is not None else "?",
        )
    )
    return app


def convert_aep_to_uvicorn_kwargs(aep: AppEntryParameters) -> dict:
    kwargs = {
        "host": aep.bind_host,
        "port": aep.bind_port,
        "use_colors": aep.logging_use_colors,
        "lifespan": "off",
        "log_level": "warning",
        "access_log": False,
        "forwarded_allow_ips": "*",
    }

    # development
    match aep.dev_mode:
        case DevMode.DEV:
            kwargs.update(
                {
                    "app": "asgi_webdav.dev.dev:app",
                    "reload": True,
                    "reload_dirs": [pathlib.Path(__file__).parent.as_posix()],
                }
            )
            return kwargs

        case DevMode.LIMTUS:
            kwargs.update(
                {
                    "app": "asgi_webdav.dev.litmus:app",
                    "host": "0.0.0.0",
                    "reload": True,
                    "reload_dirs": [pathlib.Path(__file__).parent.as_posix()],
                }
            )
            return kwargs

    # production
    kwargs.update(
        {
            "app": get_asgi_app(aep=aep),
        }
    )
    return kwargs
