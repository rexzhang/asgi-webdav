from asgi_webdav.config import Config
from asgi_webdav.middleware.http_basic_and_digest_auth import (
    HTTPAuthMiddleware,
)
from asgi_webdav.middleware.debug import DebugMiddleware
from asgi_webdav.webdav import WebDAV

config = Config.parse_obj({
    'provider_mapping': [
        {
            'prefix': '/',
            'uri': 'file:///Users/rex/p/asgi-webdav/litmus_test/test',
        },
        {
            'prefix': '/litmus/',
            'uri': 'file:///Users/rex/p/asgi-webdav/litmus_test/litmus',
        },
        {
            'prefix': '/joplin/',
            'uri': 'file:///Users/rex/p/asgi-webdav/litmus_test/joplin',
        },
    ]
})
app = WebDAV(config)
app = HTTPAuthMiddleware(
    app, username=config.username, password=config.password
)
# app = DebugMiddleware(app)
