from asgi_webdav.request import DAVRequest


def fake_call():
    pass


def create_request(
    method: str = "GET", headers: dict[bytes, bytes] = None
) -> DAVRequest:
    if headers is None:
        headers = dict()

    return DAVRequest(
        scope={
            "method": method,
            "headers": headers,
            "path": "/",
        },
        receive=fake_call,
        send=fake_call,
    )


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

    request = create_request(
        headers={
            b"range": b"bytes=-1000",
        }
    )
    assert request.content_range
    assert request.content_range_start is None
    assert request.content_range_end == 1000
