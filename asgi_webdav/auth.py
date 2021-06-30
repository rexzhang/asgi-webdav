"""
Ref:
- https://en.wikipedia.org/wiki/Basic_access_authentication
- https://en.wikipedia.org/wiki/Digest_access_authentication
- https://datatracker.ietf.org/doc/html/rfc2617
- https://datatracker.ietf.org/doc/html/rfc7616
- https://developer.mozilla.org/zh-CN/docs/Web/HTTP/Authentication
- https://developer.mozilla.org/zh-CN/docs/Web/HTTP/Headers/Digest

- https://github.com/dimagi/python-digest/blob/master/python_digest/__init__.py
- https://github.com/psf/requests/blob/master/requests/auth.py
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
from asgi_webdav.response import DAVResponse, DAVResponseType


logger = getLogger(__name__)


class HTTPAuthAbc:
    def __init__(self, realm: str):
        self.realm = realm

    def build_auth_challenge(self):
        raise NotImplementedError

    @staticmethod
    def is_credential(authorization_header: bytes) -> bool:
        raise NotImplementedError


class HTTPBasicAuth(HTTPAuthAbc):
    credential_user_mapping: dict[bytes, DAVUser] = dict()  # basic string: DAVUser

    def __init__(self, realm: str, user_mapping: dict[str, DAVUser]):
        super().__init__(realm=realm)

        for user in user_mapping.values():
            basic_credential = b64encode(
                "{}:{}".format(user.username, user.password).encode("utf-8")
            )
            self.credential_user_mapping[basic_credential] = user

    def build_auth_challenge(self) -> bytes:
        return 'Basic realm="{}"'.format(self.realm).encode("utf-8")

    @staticmethod
    def is_credential(authorization_header: bytes) -> bool:
        return authorization_header[:6].lower() == b"basic "

    def verify_user(self, authorization_header: bytes) -> Optional[DAVUser]:
        return self.credential_user_mapping.get(authorization_header[6:])


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


class HTTPDigestAuth(HTTPAuthAbc):
    def __init__(self, realm: str, secret: Optional[str] = None):
        super().__init__(realm=realm)

        if secret is None:
            self.secret = uuid4().hex
        else:
            self.secret = secret

        self.opaque = uuid4().hex.upper()

    def build_auth_challenge(self):
        return "Digest {}".format(
            self.authorization_str_build_from_data(
                {
                    "realm": self.realm,
                    "qop": "auth",
                    "nonce": self.nonce,
                    "opaque": self.opaque,
                    "algorithm": "MD5",
                    "stale": "false",
                }
            )
        ).encode("utf-8")

    @staticmethod
    def is_credential(authorization_header: bytes) -> bool:
        return authorization_header[:7].lower() == b"digest "

    @property
    def nonce(self) -> str:
        return md5("{}{}".format(uuid4().hex, self.secret).encode("utf-8")).hexdigest()

    @staticmethod
    def authorization_str_parser_to_data(authorization: str) -> dict:
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
    def authorization_str_build_from_data(data: dict[str, str]) -> str:
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
        request: DAVRequest,
        user: DAVUser,
        digest_auth_data: dict[str, str],
    ) -> str:
        ha1, ha2 = self.build_ha1_ha2_digest(
            username=user.username,
            password=user.password,
            method=request.method,
            uri=digest_auth_data.get("uri"),  # TODO!!!,
        )

        if digest_auth_data.get("qop") == "auth":
            # MD5(HA1:nonce:nonceCount:cnonce:qop:HA2)
            return self.build_md5_digest(
                [
                    ha1,
                    digest_auth_data.get("nonce"),
                    digest_auth_data.get("nc"),
                    digest_auth_data.get("cnonce"),
                    digest_auth_data.get("qop"),
                    ha2,
                ]
            )

        # MD5(HA1:nonce:HA2)
        return self.build_md5_digest(
            [
                ha1,
                digest_auth_data.get("nonce"),
                ha2,
            ]
        )

    def build_response_authentication_info_str(
        self,
        request: DAVRequest,
        user: DAVUser,
        digest_auth_data: dict[str, str],
    ) -> str:
        ha1, ha2 = self.build_ha1_ha2_digest(
            username=user.username,
            password=user.password,
            method=request.method,
            uri=digest_auth_data.get("uri"),  # TODO!!!,
        )
        rspauth = self.build_md5_digest(
            [
                ha1,
                digest_auth_data.get("nonce"),
                digest_auth_data.get("nc"),
                digest_auth_data.get("cnonce"),
                digest_auth_data.get("qop"),
                ha2,
            ]
        )
        return self.authorization_str_build_from_data(
            {
                "rspauth": rspauth,
                "qop": digest_auth_data.get("qop"),
                "cnonce": digest_auth_data.get("cnonce"),
                "nc": digest_auth_data.get("nc"),
            }
        )


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
    user_mapping: dict[str, DAVUser] = dict()  # username: password

    def __init__(self):
        config = get_config()

        for config_account in config.account_mapping:
            user = DAVUser(
                username=config_account.username,
                password=config_account.password,
                permissions=config_account.permissions,
                admin=config_account.admin,
            )

            self.user_mapping[config_account.username] = user
            logger.info("Register User: {}".format(user))

        self.basic_auth = HTTPBasicAuth(
            realm=self.realm, user_mapping=self.user_mapping
        )
        self.digest_auth = HTTPDigestAuth(realm=self.realm, secret=uuid4().hex)

    def pick_out_user(self, request: DAVRequest) -> (Optional[DAVUser], str):
        authorization_header = request.headers.get(b"authorization")
        if authorization_header is None:
            return None, "miss header: authorization"

        # Basic
        if self.basic_auth.is_credential(authorization_header):
            request.authorization_method = "Basic"

            user = self.basic_auth.verify_user(authorization_header)
            if user is None:
                return None, "no permission"

            return user, ""

        # Digest
        if self.digest_auth.is_credential(authorization_header):
            request.authorization_method = "Digest"

            digest_auth_data = self.digest_auth.authorization_str_parser_to_data(
                (authorization_header[7:].decode("utf-8"))
            )
            if len(DIGEST_AUTHORIZATION_PARAMS - set(digest_auth_data.keys())) > 0:
                return None, "no permission"

            user = self.user_mapping.get(digest_auth_data.get("username"))
            if user is None:
                return None, "no permission"

            expected_request_digest = self.digest_auth.build_request_digest(
                request=request,
                user=user,
                digest_auth_data=digest_auth_data,
            )
            request_digest = digest_auth_data.get("response")
            if expected_request_digest != request_digest:
                logger.debug(
                    f"expected_request_digest:{expected_request_digest},"
                    f" but request_digest:{request_digest}"
                )
                return None, "no permission"

            # https://datatracker.ietf.org/doc/html/rfc2617#page-15
            # macOS 11.4 finder supported
            #   WebDAVFS/3.0.0 (03008000) Darwin/20.5.0 (x86_64)
            request.authorization_info = (
                self.digest_auth.build_response_authentication_info_str(
                    request=request,
                    user=user,
                    digest_auth_data=digest_auth_data,
                )
            )
            return user, ""

        return None, "Unknown authentication method"

    def create_response_401(self, message: str) -> DAVResponse:
        headers = {b"WWW-Authenticate": self.basic_auth.build_auth_challenge()}
        # headers = {b"WWW-Authenticate": self.digest_auth.build_digest_challenge()}

        message_401 = MESSAGE_401_TEMPLATE.format(message).encode("utf-8")
        return DAVResponse(
            status=401,
            data=message_401,
            headers=headers,
            response_type=DAVResponseType.WebPage,
        )

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
