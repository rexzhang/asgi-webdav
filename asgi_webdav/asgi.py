from asgi_webdav.config import create_config_from_obj
from asgi_webdav.middleware.http_basic_and_digest_auth import (
    HTTPAuthMiddleware,
)

# from asgi_webdav.middleware.debug import DebugMiddleware
from asgi_webdav.webdav import WebDAV

# init config
config = create_config_from_obj(
    {
        "provider_mapping": [
            {
                "prefix": "/",
                "uri": "file://.",
            },
            {
                "prefix": "/litmus/",
                "uri": "memory:///",
            },
            {
                "prefix": "/litmus/fs/",
                "uri": "file://./litmus_test/litmus",
            },
            {
                "prefix": "/litmus/memory/",
                "uri": "memory:///",
            },
            {
                "prefix": "/joplin/",
                "uri": "file://./litmus_test/joplin",
            },
        ],
        "logging_level": "DEBUG",  # for debug
    }
)

app = WebDAV(config)
app = HTTPAuthMiddleware(app, username=config.username, password=config.password)
# app = DebugMiddleware(app)
