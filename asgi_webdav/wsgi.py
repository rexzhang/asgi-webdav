from wsgidav.wsgidav_app import WsgiDAVApp
# from wsgidav.http_authenticator import HTTPAuthenticator
from asgiref.wsgi import WsgiToAsgi

from asgi_webdav.middlewares.http_basic_and_digest_auth import (
    HTTPAuthMiddleware,
)
from asgi_webdav.middlewares.debug import DebugMiddleware

config = {
    "base_url": "0.0.0.0",
    "port": 8080,
    "provider_mapping": {
        "/": "/Users/rex/p/asgi-webdav/litmus_test",
    },
    "verbose": 1,

    # 'auth': 'anonymous',
    # 'middleware_stack': [
    #     'wsgidav.http_authenticator.HTTPAuthenticator',
    # ],
    # 'http_authenticator': {
    #     # Same as wsgidav.dc.simple_dc.SimpleDomainController
    #     'domain_controller': None,
    #     # Pass false to prevent sending clear text passwords
    #     'accept_basic': True,
    #     'accept_digest': True,
    #     'default_to_digest': True,
    # },
    "simple_dc": {
        "user_mapping": {
            # '*': {
            #     'test': {
            #         'password': 'test',
            #     }
            # },
            '*': True,
        }
    },
}

app = WsgiDAVApp(config)
app = WsgiToAsgi(app)
# app = HTTPAuthMiddleware(app, 'admin', 'password')
# app = DebugMiddleware(app)
