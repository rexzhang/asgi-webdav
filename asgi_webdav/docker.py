from asgi_webdav.config import update_config_from_file
from asgi_webdav.webdav import WebDAV


# init config
config = update_config_from_file()

# create ASGI app
app = WebDAV(in_docker=True)

# config sentry
if config.sentry_dsn:
    import sentry_sdk
    from sentry_sdk.integrations.asgi import SentryAsgiMiddleware

    sentry_sdk.init(dsn=config.sentry_dsn)

    app = SentryAsgiMiddleware(app)
