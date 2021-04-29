from asgi_webdav.config import create_config_from_obj

# from asgi_webdav.middleware.debug import DebugMiddleware
from asgi_webdav.webdav import WebDAV

# init config
config = create_config_from_obj(
    {
        # "auth_mapping": [{"username": "user1", "password": "pass1", "permissions": []}],
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
# app = DebugMiddleware(app)
