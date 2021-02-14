"""
Ref:
- https://tools.ietf.org/html/rfc2617
- https://en.wikipedia.org/wiki/Basic_access_authentication
- https://en.wikipedia.org/wiki/Digest_access_authentication

- https://github.com/dimagi/python-digest/blob/master/python_digest/utils.py
- https://gist.github.com/dayflower/5828503
"""

from base64 import b64encode

from asgi_webdav.constants import DAVResponse

MESSAGE_401 = b"""<!DOCTYPE html>
<html>
  <head>
    <meta charset="UTF-8" />
    <title>Error</title>
  </head>
  <body>
    <h1>401 Unauthorized.</h1>
  </body>
</html>"""


class HTTPAuthMiddleware:
    def __init__(self, app, username: str, password: str):
        self.app = app
        self.username = bytes(username, encoding='utf8')
        self.password = bytes(password, encoding='utf8')
        self.realm = b'realm'

        self.basic = b64encode(
            self.username + b':' + self.password
        )

    async def __call__(self, scope, receive, send) -> None:
        authenticated = await self.handle(scope)
        if not authenticated:
            response = DAVResponse(status=401, message=MESSAGE_401, headers=[
                # (b'WWW-Authenticate', b'Digest realm="' + self.realm + b'"'),
                (b'WWW-Authenticate', b'Basic realm="' + self.realm + b'"'),
            ])
            await response.send_in_one_call(send)
            return

        await self.app(scope, receive, send)

    async def handle(self, scope) -> bool:
        headers = scope.get('headers')
        if headers is None:
            # TODO raise
            return False

        authorization = dict(headers).get(b'authorization')
        if authorization is None:
            return False

        if authorization[:6] == b'Basic ':
            if authorization[6:] == self.basic:
                return True
            else:
                print(self.basic)
                return False

        if authorization[:6] == b'Digest':
            # TODO
            pass

        return False
