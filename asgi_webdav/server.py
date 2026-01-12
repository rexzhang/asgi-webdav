from __future__ import annotations

import logging.config
import pathlib
import sys
from logging import getLogger
from typing import Any

from asgi_middleware_static_file import ASGIMiddlewareStaticFile
from asgiref.typing import ASGIReceiveCallable, ASGISendCallable, HTTPScope

from asgi_webdav import __name__ as app_name
from asgi_webdav import __version__
from asgi_webdav.auth import DAVAuth
from asgi_webdav.config import (
    Config,
    generate_config_from_dict,
    generate_config_from_file_with_multi_suffix,
    get_global_config,
    reinit_global_config,
)
from asgi_webdav.constants import AppEntryParameters, DAVMethod, DevMode
from asgi_webdav.exceptions import DAVExceptionProviderInitFailed
from asgi_webdav.helpers import is_browser_user_agent
from asgi_webdav.log import get_dav_logging_config
from asgi_webdav.middleware.cors import ASGIMiddlewareCORS
from asgi_webdav.request import DAVRequest
from asgi_webdav.response import DAVResponse, get_dav_sender
from asgi_webdav.web_dav import WebDAV
from asgi_webdav.web_page import WebPage

logger = getLogger(__name__)


_service_abnormal_exit_message = "ASGI WebDAV Server has stopped working!"


class DAVApp:
    def __init__(self, config: Config):
        logger.info(f"ASGI WebDAV Server(v{__version__}) starting...")
        self.dav_auth = DAVAuth(config)
        try:
            self.web_dav = WebDAV(config)

        except DAVExceptionProviderInitFailed as e:
            logger.critical(e)
            logger.info(_service_abnormal_exit_message)
            sys.exit(1)

        self.web_page = WebPage()
        self.config = config

    async def __call__(
        self, scope: HTTPScope, receive: ASGIReceiveCallable, send: ASGISendCallable
    ) -> None:
        request, response = await self.handle(scope, receive, send)

        response.process(config=self.config, request=request)
        sender = get_dav_sender(config=self.config, response=response)
        if request.method in {DAVMethod.COPY, DAVMethod.MOVE}:
            logger.info(
                "%s - %s %s %s - %s - %d - %s - %s",
                request.client_ip_address,
                request.method.value,
                request.path,
                request.dst_path,
                request.authorization_method,  # Basic/Digest/[TODO:]Anonymous
                response.status,
                response.matched_sender_name.name,
                request.client_user_agent,
            )
        else:
            logger.info(
                "%s - %s %s - %s - %d - %s - %s",
                request.client_ip_address,
                request.method.value,
                request.path,
                request.authorization_method,
                response.status,
                response.matched_sender_name.name,
                request.client_user_agent,
            )
        logger.debug(request.headers)
        logger.debug(f"response header:{response.headers}")
        await sender.send_it(request.send)

    async def handle(
        self, scope: HTTPScope, receive: ASGIReceiveCallable, send: ASGISendCallable
    ) -> tuple[DAVRequest, DAVResponse]:
        # parser request
        request = DAVRequest(scope, receive, send)

        # check user auth
        message = await self.dav_auth.pick_out_user(request)
        if message is not None:
            logger.debug(request)
            return request, self.dav_auth.create_response_401(request, message)

        # process Admin request
        if (
            request.method == DAVMethod.GET
            and request.src_path.parts_count >= 1
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
            logger.debug(response)

        except DAVExceptionProviderInitFailed as e:
            logger.critical(e)
            logger.info(_service_abnormal_exit_message)
            sys.exit(1)

        if response.status == 401 and is_browser_user_agent(request.client_user_agent):
            # browser user agent, send 401 with login form
            return request, self.dav_auth.create_response_401(request, "")

        return request, response


def get_asgi_app(aep: AppEntryParameters, config_obj: dict[str, Any] | None = None):  # type: ignore
    """create ASGI app"""
    logging.config.dictConfig(get_dav_logging_config(config=get_global_config()))

    # init config
    config: Config | None = None
    if aep.config_file is not None:
        config = generate_config_from_file_with_multi_suffix(aep.config_file)
    elif config_obj is not None:
        config = generate_config_from_dict(config_obj)
    else:
        logger.warning("Init config as default value")
        config = Config()

    if config is None:
        logger.error("Init config as default value")
        config = Config()

    config.update_from_app_args_and_env_and_default_value(aep=aep)

    reinit_global_config(config)

    # init logging
    if config.logging.enable:
        logging.config.dictConfig(get_dav_logging_config(config=config))
        logger.debug(config.to_json())

    # create ASGI app
    app = DAVApp(config)

    # route /_/static
    app = ASGIMiddlewareStaticFile(
        app=app,  # type: ignore
        static_url="_/static",
        static_root_paths=[pathlib.Path(__file__).parent.joinpath("static")],
    )

    # CORS
    if config.cors.enable:
        app = ASGIMiddlewareCORS(
            app=app,  # type: ignore
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
            app = SentryAsgiMiddleware(app)  # type: ignore

        except ImportError as e:
            logger.warning(e)

    logger.info(
        "ASGI WebDAV Server running on http://{}:{} (Press CTRL+C to quit)".format(
            aep.bind_host if aep.bind_host is not None else "?",
            aep.bind_port if aep.bind_port is not None else "?",
        )
    )
    return app


def convert_aep_to_uvicorn_kwargs(aep: AppEntryParameters) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
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
