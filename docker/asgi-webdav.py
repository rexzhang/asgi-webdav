#!/usr/local/bin/python

import uvicorn

from asgi_webdav.cli import CliKwargs, convert_kwargs_from_cli2uvicorn


def main():
    cli_kwargs = CliKwargs(
        version=False,
        host="0.0.0.0",
        port=8000,
        user=(None, None),
        root_path=None,
        config="/data/webdav.json",
        dev=False,
        in_docker_container=True,
    )
    kwargs = convert_kwargs_from_cli2uvicorn(cli_kwargs)

    return uvicorn.run(**kwargs)


if __name__ == "__main__":
    main()
