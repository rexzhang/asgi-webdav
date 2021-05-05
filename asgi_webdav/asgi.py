from asgi_webdav.config import create_config_from_obj

# from asgi_webdav.middleware.debug import DebugMiddleware
from asgi_webdav.webdav import WebDAV

# init config
config = create_config_from_obj(
    {
        # "account_mapping": [
        #     {"username": "user1", "password": "pass1", "permissions": []}
        # ],
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
                "uri": "file://./test_area",
            },
            {
                "prefix": "/litmus/memory/",
                "uri": "memory:///",
            },
            {
                "prefix": "/~",
                "uri": "file://./test_area/home",
                "home_dir": True,
            },
        ],
        "logging_level": "DEBUG",  # for debug
    }
)

app = WebDAV(config)
# app = DebugMiddleware(app)
