# from asgi_webdav.middleware.debug import DebugMiddleware
from asgi_webdav.constants import AppArgs
from asgi_webdav.server import get_app

# init config
config_object = {
    "account_mapping": [
        {"username": "user_all", "password": "password", "permissions": ["+"]},
        {
            "username": "username",
            "password": "password",
            "permissions": ["+^/$", "+^/litmus", "-^/litmus/other"],
            "admin": True,
        },
        {"username": "guest", "password": "password", "permissions": list()},
    ],
    "http_digest_auth": {
        "enable": True,
        # "disable_rule": "neon/",
    },
    "provider_mapping": [
        {
            "prefix": "/",
            "uri": "file://.",
        },
        {
            "prefix": "/var_log",
            "uri": "file:///var/log",
        },
        {
            "prefix": "/litmus",
            "uri": "memory:///",
        },
        {
            "prefix": "/litmus/fs",
            "uri": "file://./test_zone/litmus",
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
            "uri": "file://./test_zone/home",
            "home_dir": True,
        },
    ],
    "guess_type_extension": {
        "enable": True,
        "enable_default_mapping": True,
        "filename_mapping": {"full_name.ext": "your/format"},
        "suffix_mapping": {".py": "text/plain"},
    },
    "text_file_charset_detect": {
        "enable": True,
    },
    "compression": {
        "level": "fast",
    },
    "dir_browser": {
        "enable": True,
        "enable_macos_ignore_rules": True,
        "enable_windows_ignore_rules": True,
        "enable_synology_ignore_rules": True,
        "user_ignore_rule": "",
    },
    "logging_level": "DEBUG",  # for debug
    # "logging_level": "INFO",  # for debug
}

app_args = AppArgs(in_docker_container=False)
app = get_app(app_args=app_args, config_obj=config_object)
# app = DebugMiddleware(app)
