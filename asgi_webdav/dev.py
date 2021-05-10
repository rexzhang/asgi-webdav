from asgi_webdav.config import update_config_from_obj

# from asgi_webdav.middleware.debug import DebugMiddleware
from asgi_webdav.webdav import WebDAV

# init config
update_config_from_obj(
    {
        "account_mapping": [
            {"username": "user_all", "password": "password", "permissions": ["+"]},
            {
                "username": "username",
                "password": "password",
                "permissions": ["+^/$", "+^/litmus", "-^/litmus/other"],
            },
            {"username": "guest", "password": "password", "permissions": list()},
        ],
        "provider_mapping": [
            {
                "prefix": "/",
                "uri": "file://.",
            },
            {
                "prefix": "/litmus",
                "uri": "memory:///",
            },
            {
                "prefix": "/litmus/fs",
                "uri": "file://./test_area/litmus",
            },
            {
                "prefix": "/litmus/memory",
                "uri": "memory:///",
            },
            {
                "prefix": "/litmus/other",
                "uri": "memory:///",
            },
            {
                "prefix": "/~",
                "uri": "file://./test_area/home",
                "home_dir": True,
            },
        ],
        "content_type": {
            "suffix_mapping": {".md": "text/plain"},
        },
        "logging_level": "DEBUG",  # for debug
    }
)

app = WebDAV()
# app = DebugMiddleware(app)
