from asgi_webdav.middleware.http_basic_and_digest_auth import (
    HTTPAuthMiddleware,
)
from asgi_webdav.middleware.debug import DebugMiddleware
from asgi_webdav.webdav import WebDAV

dist_map = {
    # prefix 需要以 / 结束
    '/': '/Users/rex/p/asgi-webdav/litmus_test/test',
    '/litmus/': '/Users/rex/p/asgi-webdav/litmus_test/litmus',
    '/joplin/': '/Users/rex/p/asgi-webdav/litmus_test/joplin',
}

app = WebDAV(dist_map)
app = HTTPAuthMiddleware(app, 'test', 'test')
# app = DebugMiddleware(app)
