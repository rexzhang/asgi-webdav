from functools import partial

from fastapi import FastAPI

from asgi_webdav.constants import DAV_METHODS, AppEntryParameters
from asgi_webdav.server import get_asgi_app as get_webdav_asgi_app

webdav_config = {
    "provider_mapping": [
        {
            "prefix": "/",
            "uri": "file://.",
        },
    ]
}
webdav_aep = AppEntryParameters()
webdav_app = get_webdav_asgi_app(aep=webdav_aep, config_obj=webdav_config)


class WebDAVApp:
    def __init__(self, app, webdav_app):
        self._app = app
        self._webdav_app = webdav_app

    async def __call__(self, scope, receive, send):
        if scope.get("method") in DAV_METHODS and scope.get("path").startswith(
            "/webdav"
        ):
            return await self._webdav_app(scope, receive, send)

        return await self._app(scope, receive, send)


app = FastAPI()
app.add_middleware(partial(WebDAVApp, webdav_app=webdav_app))
