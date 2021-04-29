from asgi_webdav.config import create_config_from_file
from asgi_webdav.webdav import WebDAV


# init config
config = create_config_from_file()

# create ASGI app
app = WebDAV(config, in_docker=True)

# config sentry
if config.sentry_dsn:
    import sentry_sdk
    from sentry_sdk.integrations.asgi import SentryAsgiMiddleware

    sentry_sdk.init(dsn=config.sentry_dsn)

    app = SentryAsgiMiddleware(app)
