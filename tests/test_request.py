from asgi_webdav.constants import ASGIScope, DAVMethod
from asgi_webdav.request import DAVRequest


async def fake_call():
    pass


async def fake_send():
    return


def create_request(
    method: str = "GET", headers: dict[bytes, bytes] = None
) -> DAVRequest:
    if headers is None:
        headers = dict()

    return DAVRequest(
        scope=ASGIScope(
            {
                "method": method,
                "headers": headers,
                "path": "/",
            }
        ),
        receive=fake_call,
        send=fake_call,
    )


def test_parser_empty_scope():
    request = DAVRequest(ASGIScope({}), fake_call, fake_send)
    assert request.method == DAVMethod.UNKNOWN


def test_parser_header_range():
    request = create_request(headers={})
    assert not request.content_range

    request = create_request(
        headers={
            b"range": b"bytes=200-1000, 2000-6576, 19000-",
        }
    )
    assert request.content_range
    assert request.content_range_start == 200
    assert request.content_range_end == 1000

    request = create_request(
        headers={
            b"range": b"bytes=200-1000",
        }
    )
    assert request.content_range
    assert request.content_range_start == 200
    assert request.content_range_end == 1000

    request = create_request(
        headers={
            b"range": b"bytes=200-",
        }
    )
    assert request.content_range
    assert request.content_range_start == 200
    assert request.content_range_end is None
