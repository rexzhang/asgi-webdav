"""
Ref:
- https://en.wikipedia.org/wiki/Basic_access_authentication
- https://tools.ietf.org/html/rfc2617
- https://en.wikipedia.org/wiki/Digest_access_authentication
- https://datatracker.ietf.org/doc/html/rfc7616

- https://github.com/dimagi/python-digest/blob/master/python_digest/utils.py
- https://gist.github.com/dayflower/5828503
"""


from typing import Optional
from base64 import b64encode
from uuid import uuid4
from hashlib import md5
from logging import getLogger

from asgi_webdav.constants import DAVUser
from asgi_webdav.config import get_config
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
    realm = "ASGI-WebDAV"

    account_mapping: dict[str, DAVUser] = dict()  # username: password
    account_basic_mapping: dict[bytes, DAVUser] = dict()  # basic string: DAVAccount

    def __init__(self):
        config = get_config()

        for config_account in config.account_mapping:
            basic = b64encode(
                "{}:{}".format(config_account.username, config_account.password).encode(
                    "utf-8"
                )
            )
            account = DAVUser(
                username=config_account.username,
                password=config_account.password,
                permissions=config_account.permissions,
            )

            self.account_mapping[config_account.username] = account
            self.account_basic_mapping[basic] = account

            logger.info("Register Account: {}".format(account))

        self.digest_auth = HTTPDigestAuth(realm=self.realm, secret=uuid4().hex)

    def pick_out_user(self, request: DAVRequest) -> (Optional[DAVUser], str):
        header_authorization = request.headers.get(b"authorization")
        if header_authorization is None:
            return None, "miss header: authorization"

        # Basic
        if header_authorization[:6] == b"Basic ":
            account = self.account_basic_mapping.get(header_authorization[6:])
            if account is None:
                return None, "no permission"

            return account, ""

        if self.digest_auth.is_digest_credential(header_authorization):
            request_data = self.digest_auth.parser_authorization_str_to_data(
                (header_authorization[7:].decode("utf-8"))
            )
            if len(DIGEST_AUTHORIZATION_PARAMS - set(request_data.keys())) > 0:
                return None, "no permission"

            account = self.account_mapping.get(request_data.get("username"))
            if account is None:
                return None, "no permission"

            expected_request_digest = self.digest_auth.build_request_digest(
                request_data=request_data,
                username=account.username,
                password=account.password,
                method=request.method,
                uri=request_data.get("uri"),  # TODO!!!
            )
            request_digest = request_data.get("response")
            if expected_request_digest != request_digest:
                logger.debug(
                    f"expected_request_digest:{expected_request_digest}, but request_digest:{request_digest}"
                )
                return None, "no permission"

            # https://datatracker.ietf.org/doc/html/rfc2617#page-15
            # macOS 11.4 finder(WebDAVFS/3.0.0 (03008000) Darwin/20.5.0 (x86_64)) supported
            request.authorization_info = (
                self.digest_auth.build_response_authentication_info_str(
                    request_data=request_data,
                    username=account.username,
                    password=account.password,
                    method=request.method,
                    uri=request_data.get("uri"),  # TODO!!!
                )
            )
            return account, ""

        return None, "Unknown authentication method"

    def create_response_401(self, message: str) -> DAVResponse:
        headers = {b"WWW-Authenticate": self.digest_auth.build_digest_challenge()}

        message_401 = MESSAGE_401_TEMPLATE.format(message).encode("utf-8")
        return DAVResponse(status=401, data=message_401, headers=headers)

    @staticmethod
    def _parser_digest_request(authorization: str) -> dict:
        values = authorization[7:].split(",")

        data = dict()
        for value in values:
            value = value.replace('"', "").replace(" ", "")
            try:
                k, v = value.split("=")
                data[k] = v
            except ValueError:
                pass

        print(data)
        return data


DIGEST_AUTHORIZATION_PARAMS = {
    "username",
    "realm",
    "nonce",
    "uri",
    "response",
    "algorithm",
    "opaque",
    "qop",
    "nc",
    "cnonce",
}


class HTTPDigestAuth:
    def __init__(self, realm: str, secret: Optional[str] = None):
        self.realm = realm
        if secret is None:
            self.secret = uuid4().hex
        else:
            self.secret = secret

        self.opaque = uuid4().hex.upper()

    @staticmethod
    def is_digest_credential(authorization_header: bytes) -> bool:
        return authorization_header[:7].lower() == b"digest "

    @property
    def nonce(self) -> str:
        return md5("{}{}".format(uuid4().hex, self.secret).encode("utf-8")).hexdigest()

    def build_digest_challenge(self):
        return 'Digest realm="{}", qop="auth", nonce="{}", opaque="{}", algorithm="MD5", stale="false"'.format(
            self.realm,
            self.nonce,
            self.opaque,
        ).encode(
            "utf-8"
        )

    @staticmethod
    def parser_authorization_str_to_data(authorization: str) -> dict:
        values = authorization.split(",")
        data = dict()
        for value in values:
            try:
                k, v = value.split("=", maxsplit=1)
                k = k.strip(" ").rstrip(" ")
                v = v.strip(' "').rstrip(' "').strip("'").rstrip("'")
                data[k] = v
            except ValueError as e:
                logger.error("parser:{} failed, ".format(value), e)

        return data

    @staticmethod
    def build_authorization_str_from_data(data: dict[str, str]) -> str:
        return ", ".join(['%s="%s"' % (k, v) for (k, v) in data.items()])

    @staticmethod
    def build_md5_digest(data: list[str]) -> str:
        return md5(":".join(data).encode("utf-8")).hexdigest()

    def build_ha1_ha2_digest(
        self, username: str, password: str, method: str, uri: str
    ) -> (str, str):
        # HA1 = MD5(username:realm:password)
        ha1 = self.build_md5_digest([username, self.realm, password])

        # HA2 = MD5(method:digestURI)
        ha2 = self.build_md5_digest([method, uri])

        return ha1, ha2

    def build_request_digest(
        self,
        request_data: dict[str, str],
        username: str,
        password: str,
        method: str,
        uri: str,
    ) -> str:
        ha1, ha2 = self.build_ha1_ha2_digest(
            username=username, password=password, method=method, uri=uri
        )

        if request_data.get("qop") == "auth":
            # MD5(HA1:nonce:nonceCount:cnonce:qop:HA2)
            return self.build_md5_digest(
                [
                    ha1,
                    request_data.get("nonce"),
                    request_data.get("nc"),
                    request_data.get("cnonce"),
                    request_data.get("qop"),
                    ha2,
                ]
            )

        # MD5(HA1:nonce:HA2)
        return self.build_md5_digest(
            [
                ha1,
                request_data.get("nonce"),
                ha2,
            ]
        )

    def build_response_authentication_info_str(
        self,
        request_data: dict[str, str],
        username: str,
        password: str,
        method: str,
        uri: str,
    ) -> str:
        ha1, ha2 = self.build_ha1_ha2_digest(
            username=username, password=password, method=method, uri=uri
        )
        rspauth = self.build_md5_digest(
            [
                ha1,
                request_data.get("nonce"),
                request_data.get("nc"),
                request_data.get("cnonce"),
                request_data.get("qop"),
                ha2,
            ]
        )
        return self.build_authorization_str_from_data(
            {
                "rspauth": rspauth,
                "qop": request_data.get("qop"),
                "cnonce": request_data.get("cnonce"),
                "nc": request_data.get("nc"),
            }
        )
