"""
Ref:
- https://tools.ietf.org/html/rfc2617
- https://en.wikipedia.org/wiki/Basic_access_authentication
- https://en.wikipedia.org/wiki/Digest_access_authentication

- https://github.com/dimagi/python-digest/blob/master/python_digest/utils.py
- https://gist.github.com/dayflower/5828503
"""


from typing import Dict, Optional
from base64 import b64encode
from logging import getLogger

from asgi_webdav.config import Config, Account
from asgi_webdav.request import DAVRequest
from asgi_webdav.response import DAVResponse


logger = getLogger(__name__)


MESSAGE_401_TEMPLATE = """<!DOCTYPE html>
<html>
  <head>
    <meta charset="UTF-8" />
    <title>Error</title>
  </head>
  <body>
    <h1>401 Unauthorized. {}</h1>
  </body>
</html>"""


class DAVAuth:
    realm = "ASGI WebDAV"

    basic_data_mapping: Dict[bytes, Account] = dict()  # Basic: AccountMapping

    def __init__(self, config: Config):
        for account in config.account_mapping:
            basic = b64encode(
                "{}:{}".format(account.username, account.password).encode("utf-8")
            )
            self.basic_data_mapping[basic] = account

            logger.info("Register Account: {}".format(account))

    def check_request(self, request: DAVRequest) -> Optional[DAVResponse]:
        authorization = request.headers.get(b"authorization")
        if authorization is None:
            return self._create_response_401("miss header: authorization")

        # Basic
        if authorization[:6] == b"Basic ":
            account = self.basic_data_mapping.get(authorization[:6])
            if account:
                if self._check_permission(request, account):
                    return None

            return self._create_response_401("no permission")

        if authorization[:6] == b"Digest":
            # TODO
            return self._create_response_401("Digest is not currently supported")

        return self._create_response_401("Unknown authentication method")

    @staticmethod
    def _check_permission(request: DAVRequest, account: Account) -> bool:
        return True

    def _create_response_401(self, message: str) -> DAVResponse:
        headers = {
            b"WWW-Authenticate": 'Basic realm="{}"'.format(self.realm).encode("utf-8")
        }
        message_401 = MESSAGE_401_TEMPLATE.format(message).encode("utf-8")
        return DAVResponse(status=401, message=message_401, headers=headers)
