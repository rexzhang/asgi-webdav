import pathlib
from collections import namedtuple
from logging import getLogger

import click
import uvicorn

from asgi_webdav.constants import AppArgs
from asgi_webdav.server import get_app


logger = getLogger(__name__)

CliKwargs = namedtuple(
    "CliKwargs",
    [
        "version",
        "host",
        "port",
        "user",
        "root_path",
        "config",
        "dev",
        "in_docker_container",
    ],
)


@click.command("runserver", help="Run ASGI WebDAV server")
@click.option(
    "-V",
    "--version",
    is_flag=True,
    default=False,
    help="Print version info and exit.",
)
@click.option(
    "-H",
    "--host",
    default="127.0.0.1",
    help="Bind socket to this host.  [default: 127.0.0.1]",
)
@click.option(
    "-P", "--port", default=8000, help="Bind socket to this port.  [default: 8000]"
)
@click.option(
    "-u",
    "--user",
    type=(str, str),
    default=(None, None),
    help="Administrator username/password. [default: username password]",
)
# @click.option(
#     "--anonymous",
#     is_flag=True,
#     default=False,
#     help="anonymous support",
# )
@click.option(
    "-r",
    "--root-path",
    default=None,
    help="Mapping provider URI to path '/'. [default: None]",
)
@click.option(
    "-c",
    "--config",
    default=None,
    help="Load configuration from file.  [default: None]",
)
@click.option(
    "--dev",
    is_flag=True,
    default=False,
    help="Enter Development mode, DON'T use it in production!",
)
@click.option(
    "--in-docker-container",
    is_flag=True,
    default=False,
    help="When work in docker container, enable it.",
)
def main(**kwargs):
    kwargs = CliKwargs(**kwargs)
    kwargs = convert_kwargs_from_cli2uvicorn(kwargs)
    logger.debug("uvicorn's kwargs:{}".format(kwargs))

    return uvicorn.run(**kwargs)


def convert_kwargs_from_cli2uvicorn(cli_kwargs: CliKwargs) -> dict:
    if cli_kwargs.version:
        from asgi_webdav import __version__

        print(__version__)
        exit()

    app_args = AppArgs(
        in_docker_container=cli_kwargs.in_docker_container,
        bind_host=cli_kwargs.host,
        bind_port=cli_kwargs.port,
    )
    if cli_kwargs.user[0] is not None:
        app_args.admin_user = cli_kwargs.user
    if cli_kwargs.root_path is not None:
        app_args.root_path = cli_kwargs.root_path

    kwargs = {
        "host": cli_kwargs.host,
        "port": cli_kwargs.port,
        "lifespan": "off",
        "log_level": "warning",
        "access_log": False,
    }

    # development
    if cli_kwargs.dev:
        kwargs.update(
            {
                "app": "asgi_webdav.dev:app",
                "reload": True,
                "reload_dirs": [pathlib.Path(__file__).parent.as_posix()],
            }
        )

        return kwargs

    # production
    if cli_kwargs.in_docker_container:
        config = "/data/webdav.json"
        kwargs.update(
            {
                "use_colors": False,
            }
        )
    else:
        config = None

    kwargs.update(
        {
            "app": get_app(app_args=app_args, config_file=config),
            "forwarded_allow_ips": "*",
        }
    )
    return kwargs
