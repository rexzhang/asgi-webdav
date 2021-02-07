from dataclasses import dataclass
import json
from typing import Optional

import requests
import xmltodict
from prettyprinter import pprint


@dataclass
class Connect:
    base_url: str
    method: str
    path: str

    headers: Optional[dict[str]]
    auth: Optional[tuple]


def call(conn):
    result = requests.request(
        conn.method, conn.base_url + conn.path,
        headers=conn.headers, auth=conn.auth
    )
    pprint(result.headers)
    print(result.content)
    if len(result.content) > 0:
        pprint(json.loads((json.dumps(xmltodict.parse(result.content)))))


def test_apache(method, path, headers=None):
    call(Connect(
        'http://192.168.200.21:55006', method, path, headers, ('test', 'test'),
    ))


def test_asgi(method, path, headers=None):
    call(Connect(
        'http://127.0.0.1:8000', method, path, headers, None
    ))


def main():
    # test_apache('PROPFIND', '/.sync/readme.txt')
    # test_apache('PROPFIND', '/.sync')
    # test_apache('PROPFIND', '/litmus', headers={'depth': '0'})
    # test_asgi('PROPFIND', '/litmus')
    # test_asgi('PROPFIND', '/dir1/file1')
    # test_asgi('PROPFIND', '/dir1', headers={'depth': '0'})
    # test_asgi('PROPFIND', '/dir1', headers={'depth': '1'})
    # test_asgi('PROPFIND', '/dir1', headers={'depth': 'infinity'})

    pass


if __name__ == '__main__':
    main()
