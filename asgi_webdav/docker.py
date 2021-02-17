import json
from os import getenv
from pathlib import Path

import uvicorn

from asgi_webdav.webdav import WebDAV
from asgi_webdav.middleware.http_basic_and_digest_auth import (
    HTTPAuthMiddleware,
)


def parser_conf(path: str) -> dict[str, str]:
    try:
        with open(Path(path).joinpath('webdav.json')) as fp:
            dist_map = json.load(fp)
            if not isinstance(dist_map, dict) or len(dist_map) == 0:
                raise ValueError

    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        dist_map = {'/': path}

    return dist_map


# config data folder
WEBDAV_DATA = getenv('WEBDAV_DATA', '/data')
app = WebDAV(parser_conf(WEBDAV_DATA))

# config auth
USERNAME = getenv('USERNAME', 'test')
PASSWORD = getenv('PASSWORD', 'test')
app = HTTPAuthMiddleware(app, username=USERNAME, password=PASSWORD)

# config sentry
SENTRY_DSN = getenv('SENTRY_DSN', '')
if SENTRY_DSN != '':
    import sentry_sdk
    from sentry_sdk.integrations.asgi import SentryAsgiMiddleware

    sentry_sdk.init(dsn=SENTRY_DSN)

    app = SentryAsgiMiddleware(app)
