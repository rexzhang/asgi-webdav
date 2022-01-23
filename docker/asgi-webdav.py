#!/usr/local/bin/python

import uvicorn

from asgi_webdav.constants import AppEntryParameters
from asgi_webdav.server import convert_aep_to_uvicorn_kwargs


def main():
    aep = AppEntryParameters(
        bind_host="0.0.0.0",
        bind_port=8000,
        config_file="/data/webdav.json",
        logging_display_datetime=False,
        logging_use_colors=False,
    )
    kwargs = convert_aep_to_uvicorn_kwargs(aep)

    return uvicorn.run(**kwargs)


if __name__ == "__main__":
    main()
