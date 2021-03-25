from asgi_webdav.config import create_config_from_file
from asgi_webdav.webdav import WebDAV
from asgi_webdav.middleware.http_basic_and_digest_auth import (
    HTTPAuthMiddleware,
)

# init config
config = create_config_from_file()

# create ASGI app
app = WebDAV(config, in_docker=True)

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
