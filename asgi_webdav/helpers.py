from typing import Optional
from datetime import datetime
from urllib.parse import urlparse

from asgi_webdav.constants import DAV_METHODS, DAVRequest


def parser_asgi_request(scope, receive, send) -> (Optional[DAVRequest], bytes):
    method = scope.get('method')
    if method not in set(DAV_METHODS):
        msg = bytes('method:{} is not support method'.format(method), 'utf8')
        return None, msg

    headers = dict(scope.get('headers'))

    src_path = scope.get('path')
    if len(src_path) == 0:
        src_path = '/'

    dst_path = headers.get(b'destination')
    if dst_path:
        dst_path = str(
            urlparse(headers.get(b'destination')).path, encoding='utf8'
        )

    return DAVRequest(
        scope=scope, receive=receive, send=send,
        headers=headers, method=method,
        src_path=src_path, dst_path=dst_path
    ), b''


async def send_response_in_one_call(
    send, status: int, message: bytes = b'',
    headers: Optional[list] = None
) -> None:
    if headers is None:
        response_headers = [
            (b'Content-Type', b'text/html'),
        ]
    else:
        response_headers = headers

    response_headers += [
        (b'Content-Length', bytes(str(len(message)), encoding='utf8')),
        (b'Date', bytes(datetime.utcnow().isoformat(), encoding='utf8')),
    ]
    await send({
        'type': 'http.response.start',
        'status': status,
        'headers': response_headers,
    })
    await send({
        'type': 'http.response.body',
        'body': message,
    })

    return
