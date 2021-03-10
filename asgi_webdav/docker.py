import uvicorn

from asgi_webdav.config import Config
from asgi_webdav.webdav import WebDAV
from asgi_webdav.middleware.http_basic_and_digest_auth import (
    HTTPAuthMiddleware,
)

# init config
config = Config()
config.update_from_file_and_env()

# create ASGI app
app = WebDAV(config)

# config auth
app = HTTPAuthMiddleware(
    app, username=config.username, password=config.password
)

# config sentry
if config.sentry_dsn:
    import sentry_sdk
    from sentry_sdk.integrations.asgi import SentryAsgiMiddleware

    sentry_sdk.init(dsn=config.sentry_dsn)

    app = SentryAsgiMiddleware(app)
