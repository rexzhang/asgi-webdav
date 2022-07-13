from asgi_webdav.config import init_config_from_obj
from asgi_webdav.constants import DAV_METHODS, AppEntryParameters
from asgi_webdav.server import get_asgi_app as get_webdav_asgi_app


async def other_asgi_app(scope, receive, send):
    assert scope["type"] == "http"

    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [
                [b"content-type", b"text/plain"],
            ],
        }
    )
    await send(
        {
            "type": "http.response.body",
            "body": b"Hello, world!",
        }
    )


webdav_config = {
    "provider_mapping": [
        {
            "prefix": "/",
            "uri": "file://.",
        },
    ]
}
init_config_from_obj(webdav_config)
webdav_aep = AppEntryParameters()

webdav_app = get_webdav_asgi_app(aep=webdav_aep)


async def app(scope, receive, send):
    if scope.get("method") in DAV_METHODS and scope.get("path").startswith("/webdav"):
        await webdav_app(scope, receive, send)

    await other_asgi_app(scope, receive, send)
