from asgi_webdav.constants import AppEntryParameters
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


webdav_app = get_webdav_asgi_app(
    aep=AppEntryParameters(),
    config_obj={
        "provider_mapping": [
            {
                "prefix": "/webdav",
                "uri": "file://.",
            },
        ],
        "anonymous": {
            "enable": True,
        },
    },
)


async def app(scope, receive, send):
    if scope.get("path").startswith("/webdav"):
        await webdav_app(scope, receive, send)
        return

    await other_asgi_app(scope, receive, send)


"""
run:
    uvicorn work_together_with_other_asgi_app:app

then:
    open http://127.0.0.1:8000 visit other_asgi_app
    open http://127.0.0.1:8000/webdav visit WebDAV
"""
