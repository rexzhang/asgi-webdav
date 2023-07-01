from asgi_webdav.constants import AppEntryParameters
from asgi_webdav.server import get_asgi_app

config_object = {
    "account_mapping": [
        {
            "username": "username",
            "password": "password",
            "permissions": ["+"],
            "admin": True,
        }
    ],
    "provider_mapping": [
        {
            "prefix": "/",
            "uri": "memory:///",
            "read_only": True,
        },
        {
            "prefix": "/provider",
            "uri": "memory:///",
            "read_only": True,
        },
        {
            "prefix": "/provider/fs",
            "uri": "file:///tmp",
        },
        {
            "prefix": "/provider/memory",
            "uri": "memory:///",
        },
    ],
}


aep = AppEntryParameters()
app = get_asgi_app(aep=aep, config_obj=config_object)
