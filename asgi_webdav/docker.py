from asgi_webdav.config import get_config
from asgi_webdav.server import get_app


app = get_app(config_file="/data/webdav.json", in_docker=True)

# config sentry
config = get_config()
if config.sentry_dsn:
    import sentry_sdk
    from sentry_sdk.integrations.asgi import SentryAsgiMiddleware

    sentry_sdk.init(dsn=config.sentry_dsn)

    app = SentryAsgiMiddleware(app)
