# from asgi_webdav.middleware.debug import DebugMiddleware
from asgi_webdav.constants import AppEntryParameters
from asgi_webdav.server import get_asgi_app

# init config
config_object = {
    "account_mapping": [
        {
            "username": "username",
            "password": "password",
            "permissions": ["+"],
            "admin": True,
        },
        {
            "username": "user-hashlib",  # password:password
            "password": "<hashlib>:sha256:salt:"
            "291e247d155354e48fec2b579637782446821935fc96a5a08a0b7885179c408b",
            "permissions": ["+^/$"],
        },
        {
            "username": "user-digest",  # password:password
            "password": "<digest>:ASGI-WebDAV:c1d34f1e0f457c4de05b7468d5165567",
            "permissions": ["+^/$"],
        },
        {
            "username": "user-ldap",  # password:password
            "password": "<ldap>#1#ldaps://rexzhang.myds.me#SIMPLE#"
            "uid=user-ldap,cn=users,dc=rexzhang,dc=myds,dc=me",
            "permissions": ["+^/$"],
        },
        {
            "username": "litmus",
            "password": "password",
            "permissions": ["+^/$", "+^/litmus", "-^/litmus/other"],
        },
        {"username": "guest", "password": "password", "permissions": list()},
    ],
    "http_digest_auth": {
        "enable": True,
        # "disable_rule": "neon/",
        "enable_rule": "Microsoft-WebDAV-MiniRedir|TEST",
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
    # "enable_dir_browser": False,
    "logging_level": "DEBUG",  # for debug
    "sentry_dsn": "http://public@127.0.0.1:5000/1",
}

aep = AppEntryParameters()
app = get_asgi_app(aep=aep, config_obj=config_object)
# app = DebugMiddleware(app)
