from typing import Optional, Callable
from datetime import datetime
from urllib.parse import urlparse
from xml.dom.minidom import parseString as parser_xml_from_str

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


async def receive_all_data_in_one_call(receive: Callable) -> bytes:
    data = b''
    more_body = True
    while more_body:
        request_data = await receive()
        data += request_data.get('body', b'')
        more_body = request_data.get('more_body')

    return data


class DateTime:
    def __init__(self, timestamp: float):
        self.datetime = datetime.fromtimestamp(timestamp)

    def iso_850(self) -> str:
        return self.datetime.strftime(
            '%a, %d %b %Y %H:%M:%S GMT'
        )

    def iso_8601(self) -> str:
        return self.datetime.isoformat()[:19] + 'Z'





def pprint_xml(xml_str):
    xml = parser_xml_from_str(xml_str).toprettyxml()
    print(xml)
