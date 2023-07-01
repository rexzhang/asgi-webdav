import json
import xml
from dataclasses import dataclass

import requests
import xmltodict
from icecream import ic
from requests.auth import AuthBase, HTTPBasicAuth, HTTPDigestAuth


@dataclass
class Connect:
    base_url: str
    method: str
    path: str

    headers: Optional[dict[str, str]]
    auth: AuthBase


def call(status_code, conn):
    result = requests.request(
        conn.method, conn.base_url + conn.path, headers=conn.headers, auth=conn.auth
    )
    if result.status_code == status_code:
        print("pass")
        return

    print("=====================")
    ic(conn)
    ic(result)
    ic(result.headers)
    if len(result.content) > 0:
        try:
            ic(json.loads(json.dumps(xmltodict.parse(result.content))))
        except xml.parsers.expat.ExpatError:
            pass
    else:
        ic(result.content)
    print("---------------------")
    exit()


def http_basic_auth(
    status_code, method, path, headers=None, username="username", password="password"
):
    call(
        status_code,
        Connect(
            "http://127.0.0.1:8000",
            method,
            path,
            headers,
            HTTPBasicAuth(username, password),
        ),
    )


def http_digest_auth(
    status_code, method, path, headers=None, username="username", password="password"
):
    call(
        status_code,
        Connect(
            "http://127.0.0.1:8000",
            method,
            path,
            headers,
            HTTPDigestAuth(username, password),
        ),
    )


def main_test_http_client_agent():
    http_digest_auth(200, "GET", "/", headers={"user-agent": "TEST-AGENT"})


def main_test_http_basic_auth():
    # ldap
    http_basic_auth(200, "OPTIONS", "/", username="user-ldap", password="Pass1234")
    # ldap - hit cache
    http_basic_auth(200, "OPTIONS", "/", username="user-ldap", password="Pass1234")
    http_basic_auth(200, "OPTIONS", "/", username="user-ldap", password="Pass1234")


def main_test_http_digest_auth():
    http_digest_auth(200, "OPTIONS", "/")
    http_digest_auth(401, "OPTIONS", "/", password="bad-password")
    http_digest_auth(200, "OPTIONS", "/", username="user-digest")
    http_digest_auth(
        401, "OPTIONS", "/", username="user-digest", password="bad-password"
    )


if __name__ == "__main__":
    main_test_http_client_agent()
    main_test_http_basic_auth()
    main_test_http_digest_auth()
