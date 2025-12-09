from .asgi_test_kit import create_dav_request_object


def test_parser_header_range():
    request = create_dav_request_object(headers={})
    assert not request.content_range

    request = create_dav_request_object(
        headers={
            "range": "bytes=200-1000, 2000-6576, 19000-",
        }
    )
    assert request.content_range
    assert request.content_range_start == 200
    assert request.content_range_end == 1000

    request = create_dav_request_object(
        headers={
            "range": "bytes=200-1000",
        }
    )
    assert request.content_range
    assert request.content_range_start == 200
    assert request.content_range_end == 1000

    request = create_dav_request_object(
        headers={
            "range": "bytes=200-",
        }
    )
    assert request.content_range
    assert request.content_range_start == 200
    assert request.content_range_end is None
