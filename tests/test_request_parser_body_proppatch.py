from .testkit_asgi import create_dav_request_object


async def test_incorrect_input():
    request = create_dav_request_object()

    request.body = b""
    assert await request._parser_body_proppatch() is False


async def test_put_prop():
    request = create_dav_request_object()

    request.body = b'<?xml version="1.0" encoding="utf-8" ?>\n<D:propertyupdate xmlns:D="DAV:"><D:set><D:prop><prop0 xmlns="http://example.com/neon/litmus/">value0</prop0></D:prop></D:set>\n<D:set><D:prop><prop1 xmlns="http://example.com/neon/litmus/">value1</prop1></D:prop></D:set>\n<D:set><D:prop><prop2 xmlns="http://example.com/neon/litmus/">value2</prop2></D:prop></D:set>\n<D:set><D:prop><prop3 xmlns="http://example.com/neon/litmus/">value3</prop3></D:prop></D:set>\n<D:set><D:prop><prop4 xmlns="http://example.com/neon/litmus/">value4</prop4></D:prop></D:set>\n<D:set><D:prop><prop5 xmlns="http://example.com/neon/litmus/">value5</prop5></D:prop></D:set>\n<D:set><D:prop><prop6 xmlns="http://example.com/neon/litmus/">value6</prop6></D:prop></D:set>\n<D:set><D:prop><prop7 xmlns="http://example.com/neon/litmus/">value7</prop7></D:prop></D:set>\n<D:set><D:prop><prop8 xmlns="http://example.com/neon/litmus/">value8</prop8></D:prop></D:set>\n<D:set><D:prop><prop9 xmlns="http://example.com/neon/litmus/">value9</prop9></D:prop></D:set>\n</D:propertyupdate>\n'

    await request._parser_body_proppatch()
    assert request.proppatch_entries == [
        (("http://example.com/neon/litmus/", "prop0"), "value0", True),
        (("http://example.com/neon/litmus/", "prop1"), "value1", True),
        (("http://example.com/neon/litmus/", "prop2"), "value2", True),
        (("http://example.com/neon/litmus/", "prop3"), "value3", True),
        (("http://example.com/neon/litmus/", "prop4"), "value4", True),
        (("http://example.com/neon/litmus/", "prop5"), "value5", True),
        (("http://example.com/neon/litmus/", "prop6"), "value6", True),
        (("http://example.com/neon/litmus/", "prop7"), "value7", True),
        (("http://example.com/neon/litmus/", "prop8"), "value8", True),
        (("http://example.com/neon/litmus/", "prop9"), "value9", True),
    ]


async def test_PROPFIND_prop2():
    request = create_dav_request_object()
    request.body = b'<?xml version="1.0" encoding="utf-8" ?>\n<D:propertyupdate xmlns:D="DAV:"><D:remove><D:prop><prop0 xmlns="http://example.com/neon/litmus/"></prop0></D:prop></D:remove>\n<D:remove><D:prop><prop1 xmlns="http://example.com/neon/litmus/"></prop1></D:prop></D:remove>\n<D:remove><D:prop><prop2 xmlns="http://example.com/neon/litmus/"></prop2></D:prop></D:remove>\n<D:remove><D:prop><prop3 xmlns="http://example.com/neon/litmus/"></prop3></D:prop></D:remove>\n<D:remove><D:prop><prop4 xmlns="http://example.com/neon/litmus/"></prop4></D:prop></D:remove>\n<D:set><D:prop><prop5 xmlns="http://example.com/neon/litmus/">value5</prop5></D:prop></D:set>\n<D:set><D:prop><prop6 xmlns="http://example.com/neon/litmus/">value6</prop6></D:prop></D:set>\n<D:set><D:prop><prop7 xmlns="http://example.com/neon/litmus/">value7</prop7></D:prop></D:set>\n<D:set><D:prop><prop8 xmlns="http://example.com/neon/litmus/">value8</prop8></D:prop></D:set>\n<D:set><D:prop><prop9 xmlns="http://example.com/neon/litmus/">value9</prop9></D:prop></D:set>\n</D:propertyupdate>\n'

    await request._parser_body_proppatch()
    assert request.proppatch_entries == [
        (("http://example.com/neon/litmus/", "prop0"), "None", False),
        (("http://example.com/neon/litmus/", "prop1"), "None", False),
        (("http://example.com/neon/litmus/", "prop2"), "None", False),
        (("http://example.com/neon/litmus/", "prop3"), "None", False),
        (("http://example.com/neon/litmus/", "prop4"), "None", False),
        (("http://example.com/neon/litmus/", "prop5"), "value5", True),
        (("http://example.com/neon/litmus/", "prop6"), "value6", True),
        (("http://example.com/neon/litmus/", "prop7"), "value7", True),
        (("http://example.com/neon/litmus/", "prop8"), "value8", True),
        (("http://example.com/neon/litmus/", "prop9"), "value9", True),
    ]


async def test_PROPFIND_prop2_2():
    request = create_dav_request_object()
    request.body = b'<?xml version="1.0" encoding="utf-8" ?><propertyupdate xmlns="DAV:"><set><prop><nonamespace xmlns="">randomvalue</nonamespace></prop></set></propertyupdate>'

    await request._parser_body_proppatch()
    assert request.proppatch_entries == [(("", "nonamespace"), "randomvalue", True)]


async def test_PROPFIND_prop2_3():
    request = create_dav_request_object()
    request.body = b"<?xml version=\"1.0\" encoding=\"utf-8\" ?><propertyupdate xmlns='DAV:'><set><prop><high-unicode xmlns='http://example.com/neon/litmus/'>&#65536;</high-unicode></prop></set></propertyupdate>"

    await request._parser_body_proppatch()
    assert request.proppatch_entries == [
        (("http://example.com/neon/litmus/", "high-unicode"), "𐀀", True)
    ]


async def test_PROPFIND_prop2_4():
    request = create_dav_request_object()
    request.body = b"<?xml version=\"1.0\" encoding=\"utf-8\" ?><propertyupdate xmlns='DAV:'><remove><prop><removeset xmlns='http://example.com/neon/litmus/'/></prop></remove><set><prop><removeset xmlns='http://example.com/neon/litmus/'>x</removeset></prop></set><set><prop><removeset xmlns='http://example.com/neon/litmus/'>y</removeset></prop></set></propertyupdate>"

    await request._parser_body_proppatch()
    assert request.proppatch_entries == [
        (("http://example.com/neon/litmus/", "removeset"), "None", False),
        (("http://example.com/neon/litmus/", "removeset"), "x", True),
        (("http://example.com/neon/litmus/", "removeset"), "y", True),
    ]


async def test_PROPFIND_prop2_5():
    request = create_dav_request_object()
    request.body = b"<?xml version=\"1.0\" encoding=\"utf-8\" ?><propertyupdate xmlns='DAV:'><set><prop><removeset xmlns='http://example.com/neon/litmus/'>x</removeset></prop></set><remove><prop><removeset xmlns='http://example.com/neon/litmus/'/></prop></remove></propertyupdate>"

    await request._parser_body_proppatch()
    assert request.proppatch_entries == [
        (("http://example.com/neon/litmus/", "removeset"), "x", True),
        (("http://example.com/neon/litmus/", "removeset"), "None", False),
    ]


async def test_PROPFIND_prop2_6():
    request = create_dav_request_object()
    request.body = b"<?xml version=\"1.0\" encoding=\"utf-8\" ?><propertyupdate xmlns='DAV:'><set><prop><t:valnspace xmlns:t='http://example.com/neon/litmus/'><foo xmlns='http://bar'/></t:valnspace></prop></set></propertyupdate>"

    await request._parser_body_proppatch()
    assert request.proppatch_entries == [
        (("http://example.com/neon/litmus/", "valnspace"), "foo", True)
    ]


async def test_put_prop_2():
    request = create_dav_request_object()
    request.body = b'<?xml version="1.0" encoding="utf-8" ?>\n<D:propertyupdate xmlns:D="DAV:"><D:set><D:prop><somename xmlns="http://example.com/alpha">manynsvalue</somename></D:prop></D:set>\n<D:set><D:prop><somename xmlns="http://example.com/beta">manynsvalue</somename></D:prop></D:set>\n<D:set><D:prop><somename xmlns="http://example.com/gamma">manynsvalue</somename></D:prop></D:set>\n<D:set><D:prop><somename xmlns="http://example.com/delta">manynsvalue</somename></D:prop></D:set>\n<D:set><D:prop><somename xmlns="http://example.com/epsilon">manynsvalue</somename></D:prop></D:set>\n<D:set><D:prop><somename xmlns="http://example.com/zeta">manynsvalue</somename></D:prop></D:set>\n<D:set><D:prop><somename xmlns="http://example.com/eta">manynsvalue</somename></D:prop></D:set>\n<D:set><D:prop><somename xmlns="http://example.com/theta">manynsvalue</somename></D:prop></D:set>\n<D:set><D:prop><somename xmlns="http://example.com/iota">manynsvalue</somename></D:prop></D:set>\n<D:set><D:prop><somename xmlns="http://example.com/kappa">manynsvalue</somename></D:prop></D:set>\n</D:propertyupdate>\n'

    await request._parser_body_proppatch()
    assert request.proppatch_entries == [
        (("http://example.com/alpha", "somename"), "manynsvalue", True),
        (("http://example.com/beta", "somename"), "manynsvalue", True),
        (("http://example.com/gamma", "somename"), "manynsvalue", True),
        (("http://example.com/delta", "somename"), "manynsvalue", True),
        (("http://example.com/epsilon", "somename"), "manynsvalue", True),
        (("http://example.com/zeta", "somename"), "manynsvalue", True),
        (("http://example.com/eta", "somename"), "manynsvalue", True),
        (("http://example.com/theta", "somename"), "manynsvalue", True),
        (("http://example.com/iota", "somename"), "manynsvalue", True),
        (("http://example.com/kappa", "somename"), "manynsvalue", True),
    ]


async def test_COPY_notlocked():
    request = create_dav_request_object()
    request.body = b'<?xml version="1.0" encoding="utf-8" ?>\n<D:propertyupdate xmlns:D="DAV:"><D:set><D:prop><random xmlns="http://webdav.org/neon/litmus/">foobar</random></D:prop></D:set>\n</D:propertyupdate>\n'

    await request._parser_body_proppatch()
    assert request.proppatch_entries == [
        (("http://webdav.org/neon/litmus/", "random"), "foobar", True)
    ]
