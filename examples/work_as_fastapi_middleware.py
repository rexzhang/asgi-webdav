from functools import partial

from fastapi import FastAPI

from asgi_webdav.constants import AppEntryParameters
from asgi_webdav.server import get_asgi_app as get_webdav_asgi_app

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


class WebDAVApp:
    def __init__(self, app, webdav_app):
        self._app = app
        self._webdav_app = webdav_app

    async def __call__(self, scope, receive, send):
        if scope.get("path").startswith("/webdav"):
            return await self._webdav_app(scope, receive, send)

        return await self._app(scope, receive, send)


app = FastAPI()


@app.get("/")
def read_root():
    return {"Hello": "World"}


app.add_middleware(partial(WebDAVApp, webdav_app=webdav_app))

"""
run:
    uvicorn work_as_fastapi_middleware:app

then:
    open http://127.0.0.1:8000 visit fastapi app
    open http://127.0.0.1:8000/webdav visit WebDAV
"""
