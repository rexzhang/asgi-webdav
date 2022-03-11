from logging import getLogger

import click
import uvicorn

from asgi_webdav.constants import AppEntryParameters
from asgi_webdav.server import convert_aep_to_uvicorn_kwargs

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
    "-c",
    "--config",
    default=None,
    help="Load configuration from file.  [default: None]",
)
@click.option(
    "-u",
    "--user",
    type=(str, str),
    default=None,
    help="Administrator username/password. [default: username password]",
)
@click.option(
    "-r",
    "--root-path",
    default=None,
    help="Mapping provider URI to path '/'. [default: None]",
)
@click.option(
    "--dev",
    is_flag=True,
    default=False,
    help="Enter Development mode, DON'T use it in production!",
)
def main(**kwargs):
    if kwargs["version"]:
        from asgi_webdav import __version__

        print(__version__)
        exit()

    aep = convert_click_kwargs_to_aep(kwargs)
    kwargs = convert_aep_to_uvicorn_kwargs(aep)
    logger.debug(f"uvicorn's kwargs:{kwargs}")

    return uvicorn.run(**kwargs)


def convert_click_kwargs_to_aep(kwargs: dict) -> AppEntryParameters:
    return AppEntryParameters(
        bind_host=kwargs["host"],
        bind_port=kwargs["port"],
        config_file=kwargs["config"],
        admin_user=kwargs["user"],
        root_path=kwargs["root_path"],
        dev_mode=kwargs["dev"],
    )
