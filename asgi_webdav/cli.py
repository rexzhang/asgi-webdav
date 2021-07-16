import pathlib
from logging import getLogger

import click
import uvicorn

from asgi_webdav.constants import AppArgs
from asgi_webdav.server import get_app


logger = getLogger(__name__)


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
def cli(version, host, port, user, root_path, config, dev, in_docker_container):
    kwargs = cli_kwargs_parser(
        version, host, port, user, root_path, config, dev, in_docker_container
    )

    logger.debug("uvicorn's kwargs:{}".format(kwargs))
    return uvicorn.run(**kwargs)


def cli_kwargs_parser(
    version, host, port, user, root_path, config, dev, in_docker_container
) -> dict:
    if version:
        from asgi_webdav import __version__

        print(__version__)
        exit()

    app_args = AppArgs(
        in_docker_container=in_docker_container, bind_host=host, bind_port=port
    )
    if user[0] is not None:
        app_args.admin_user = user
    if root_path is not None:
        app_args.root_path = root_path

    kwargs = {
        "host": host,
        "port": port,
        "lifespan": "off",
        "log_level": "warning",
        "access_log": False,
    }

    # development
    if dev:
        kwargs.update(
            {
                "app": "asgi_webdav.dev:app",
                "reload": True,
                "reload_dirs": [pathlib.Path(__file__).parent.as_posix()],
            }
        )

        return kwargs

    # production
    if in_docker_container:
        config = "/data/webdav.json"

    kwargs.update(
        {
            "app": get_app(app_args=app_args, config_file=config),
            "forwarded_allow_ips": "*",
        }
    )
    return kwargs


if __name__ == "__main__":
    cli()
