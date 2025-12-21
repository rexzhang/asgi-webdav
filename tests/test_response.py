from asgi_webdav.response import DAVResponse


def test_can_be_compressed():
    assert DAVResponse._can_be_compressed("text/plain", "")
    assert DAVResponse._can_be_compressed("text/html; charset=utf-8", "")
    assert DAVResponse._can_be_compressed("dont/compress", "") is False

    assert DAVResponse._can_be_compressed("compress/please", "compress")
    assert DAVResponse._can_be_compressed("compress/please", "decompress") is False
