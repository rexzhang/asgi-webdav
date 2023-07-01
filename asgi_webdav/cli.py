from logging import getLogger

import click

try:
    import uvicorn
except ImportError:
    uvicorn = None

from asgi_webdav.constants import AppEntryParameters, DevMode
from asgi_webdav.server import convert_aep_to_uvicorn_kwargs

logger = getLogger(__name__)


def convert_click_kwargs_to_aep(kwargs: dict) -> AppEntryParameters:
    if kwargs.get("dev"):
        dev_mode = DevMode.DEV
    elif kwargs.get("litmus"):
        dev_mode = DevMode.LIMTUS
    else:
        dev_mode = None

    aep = AppEntryParameters(
        bind_host=kwargs["host"],
        bind_port=kwargs["port"],
        config_file=kwargs["config"],
        admin_user=kwargs["user"],
        root_path=kwargs["root_path"],
        dev_mode=dev_mode,
        logging_display_datetime=kwargs["logging_display_datetime"],
        logging_use_colors=kwargs["logging_display_datetime"],
    )

    return aep


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
    "--logging-display-datetime/--logging-no-display-datetime",
    is_flag=True,
    default=True,
    help="Turn on datetime in logging",
)
@click.option(
    "--logging-use-colors/--logging-no-use-colors",
    is_flag=True,
    default=True,
    help="Turn on color in logging",
)
@click.option(
    "--dev",
    is_flag=True,
    default=False,
    help="Enter Development(for coding) mode, DON'T use it in production!",
)
@click.option(
    "--litmus",
    is_flag=True,
    default=False,
    help="Enter Litmus(for test) mode, DON'T use it in production!",
)
def main(**kwargs):
    if kwargs["version"]:
        from asgi_webdav import __version__

        print(__version__)
        exit()

    if uvicorn is None:
        print(
            "Please install ASGI web server implementation first.\n"
            "  eg: pip install -U ASGIWebDAV[uvicorn]"
        )
        exit(1)

    aep = convert_click_kwargs_to_aep(kwargs)
    kwargs = convert_aep_to_uvicorn_kwargs(aep)
    logger.debug(f"uvicorn's kwargs:{kwargs}")

    return uvicorn.run(**kwargs)
