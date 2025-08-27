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
            "ignore_property_extra": False,
        },
        {
            "prefix": "/provider",
            "uri": "memory:///",
            "read_only": True,
            "ignore_property_extra": False,
        },
        {
            "prefix": "/provider/fs",
            "uri": "file:///tmp",
            "ignore_property_extra": False,
        },
        {
            "prefix": "/provider/memory",
            "uri": "memory:///",
            "ignore_property_extra": False,
        },
    ],
}


aep = AppEntryParameters()
app = get_asgi_app(aep=aep, config_obj=config_object)
