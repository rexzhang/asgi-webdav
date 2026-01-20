import pytest
from icecream import ic

from asgi_webdav.middleware.cors import ASGIMiddlewareCORS

from .testkit_asgi import ASGIApp, ASGITestClient


def get_middleware_app(middleware, **kwargs):
    if "app_response_header" in kwargs:
        app_response_header = {
            k.encode("utf-8"): v.encode("utf-8")
            for k, v in kwargs.pop("app_response_header").items()
        }
        return middleware(ASGIApp(app_response_header), **kwargs)
    else:
        return middleware(ASGIApp(), **kwargs)


@pytest.mark.asyncio
async def test_cors_allow_all():
    client = ASGITestClient(
        get_middleware_app(
            ASGIMiddlewareCORS,
            allow_url_regex=None,
            allow_origins=["*"],
            allow_headers=["*"],
            allow_methods=["*"],
            expose_headers=["X-Status"],
            allow_credentials=True,
        )
    )

    # Test pre-flight response
    headers = {
        b"Origin": b"https://example.org",
        b"Access-Control-Request-Method": b"GET",
        b"Access-Control-Request-Headers": b"X-Example",
    }
    response = await client.options("/", headers=headers)
    assert response.status_code == 200
    assert response.text == "OK"
    assert response.headers[b"access-control-allow-origin"] == b"https://example.org"
    assert response.headers[b"access-control-allow-headers"] == b"X-Example"
    assert response.headers[b"access-control-allow-credentials"] == b"true"
    assert response.headers[b"vary"] == b"Origin"

    # Test standard response
    headers = {b"Origin": b"https://example.org"}
    response = await client.get("/", headers=headers)
    ic("in test", response)
    assert response.status_code == 200
    assert response.text == "Hello, World!"
    assert response.headers[b"access-control-allow-origin"] == b"*"
    assert response.headers[b"access-control-expose-headers"] == b"x-status"
    assert response.headers[b"access-control-allow-credentials"] == b"true"

    # Test standard credentialed response
    headers = {b"Origin": b"https://example.org", b"Cookie": b"star_cookie=sugar"}
    response = await client.get("/", headers=headers)
    ic("in test", response)
    assert response.status_code == 200
    assert response.text == "Hello, World!"
    assert response.headers[b"access-control-allow-origin"] == b"https://example.org"
    assert response.headers[b"access-control-expose-headers"] == b"x-status"
    assert response.headers[b"access-control-allow-credentials"] == b"true"

    # Test non-CORS response
    response = await client.get("/")
    assert response.status_code == 200
    assert response.text == "Hello, World!"
    assert b"access-control-allow-origin" not in response.headers


@pytest.mark.asyncio
async def test_cors_allow_all_except_credentials():
    client = ASGITestClient(
        get_middleware_app(
            ASGIMiddlewareCORS,
            allow_origins=["*"],
            allow_headers=["*"],
            allow_methods=["*"],
            expose_headers=["X-Status"],
        )
    )

    # Test pre-flight response
    headers = {
        b"Origin": b"https://example.org",
        b"Access-Control-Request-Method": b"GET",
        b"Access-Control-Request-Headers": b"X-Example",
    }
    response = await client.options("/", headers=headers)
    assert response.status_code == 200
    assert response.text == "OK"
    assert response.headers[b"access-control-allow-origin"] == b"*"
    assert response.headers[b"access-control-allow-headers"] == b"X-Example"
    assert b"access-control-allow-credentials" not in response.headers
    assert b"vary" not in response.headers

    # Test standard response
    headers = {b"Origin": b"https://example.org"}
    response = await client.get("/", headers=headers)
    assert response.status_code == 200
    assert response.text == "Hello, World!"
    assert response.headers[b"access-control-allow-origin"] == b"*"
    assert response.headers[b"access-control-expose-headers"] == b"x-status"
    assert b"access-control-allow-credentials" not in response.headers

    # Test non-CORS response
    response = await client.get("/")
    assert response.status_code == 200
    assert response.text == "Hello, World!"
    assert b"access-control-allow-origin" not in response.headers


@pytest.mark.asyncio
async def test_cors_allow_url_regex():
    headers = {
        b"origin": b"https://example.org",
        b"access-control-request-method": b"GET",
        b"access-control-request-headers": b"X-Example",
    }

    client = ASGITestClient(
        get_middleware_app(
            ASGIMiddlewareCORS,
            allow_url_regex="^/cors_path.*",
            allow_origins=["*"],
            allow_headers=["*"],
            allow_methods=["*"],
        )
    )
    response = await client.get("/not_cors_path", headers=headers)
    assert response.status_code == 200
    assert response.text == "Hello, World!"
    assert b"access-control-allow-origin" not in response.headers

    response = await client.get("/cors_path", headers=headers)
    assert response.status_code == 200
    assert response.text == "Hello, World!"
    assert b"access-control-allow-origin" in response.headers
    response = await client.get("/cors_path/", headers=headers)
    assert response.status_code == 200
    assert response.text == "Hello, World!"
    assert b"access-control-allow-origin" in response.headers
    response = await client.get("/cors_path/sub", headers=headers)
    assert response.status_code == 200
    assert response.text == "Hello, World!"
    assert b"access-control-allow-origin" in response.headers

    client = ASGITestClient(
        get_middleware_app(
            ASGIMiddlewareCORS,
            allow_url_regex="^/cors_path/.*",
            allow_origins=["*"],
            allow_headers=["*"],
            allow_methods=["*"],
        )
    )
    response = await client.get("/cors_path", headers=headers)
    assert response.status_code == 200
    assert response.text == "Hello, World!"
    assert b"access-control-allow-origin" not in response.headers
    response = await client.get("/cors_path/", headers=headers)
    assert response.status_code == 200
    assert response.text == "Hello, World!"
    assert b"access-control-allow-origin" in response.headers
    response = await client.get("/cors_path/sub", headers=headers)
    assert response.status_code == 200
    assert response.text == "Hello, World!"
    assert b"access-control-allow-origin" in response.headers


@pytest.mark.asyncio
async def test_cors_allow_specific_origin():
    client = ASGITestClient(
        get_middleware_app(
            ASGIMiddlewareCORS,
            allow_origins=["https://example.org"],
            allow_headers=["X-Example", "Content-Type"],
        )
    )

    # Test pre-flight response
    headers = {
        b"origin": b"https://example.org",
        b"access-control-request-method": b"GET",
        b"access-control-request-headers": b"X-Example, Content-Type",
    }
    response = await client.options("/", headers=headers)
    assert response.status_code == 200
    assert response.text == "OK"
    assert response.headers[b"access-control-allow-origin"] == b"https://example.org"
    assert response.headers[b"access-control-allow-headers"] == (
        b"accept, accept-language, content-language, content-type, x-example"
    )
    assert b"access-control-allow-credentials" not in response.headers

    # Test standard response
    headers = {b"origin": b"https://example.org"}
    response = await client.get("/", headers=headers)
    assert response.status_code == 200
    assert response.text == "Hello, World!"
    assert response.headers[b"access-control-allow-origin"] == b"https://example.org"
    assert b"access-control-allow-credentials" not in response.headers

    # Test non-CORS response
    response = await client.get("/")
    assert response.status_code == 200
    assert response.text == "Hello, World!"
    assert b"access-control-allow-origin" not in response.headers


@pytest.mark.asyncio
async def test_cors_disallowed_preflight():
    client = ASGITestClient(
        get_middleware_app(
            ASGIMiddlewareCORS,
            allow_origins=["https://example.org"],
            allow_headers=["X-Example"],
        )
    )

    # Test pre-flight response
    headers = {
        b"origin": b"https://another.org",
        b"access-control-request-method": b"POST",
        b"access-control-request-headers": b"X-Nope",
    }
    response = await client.options("/", headers=headers)
    assert response.status_code == 400
    assert response.text == "Disallowed CORS origin, method, headers"
    assert b"access-control-allow-origin" not in response.headers

    # Bug specific test, https://github.com/encode/starlette/pull/1199
    # Test preflight response text with multiple disallowed headers
    headers = {
        b"origin": b"https://example.org",
        b"access-control-request-method": b"GET",
        b"access-control-request-headers": b"X-Nope-1, X-Nope-2",
    }
    response = await client.options("/", headers=headers)
    assert response.text == "Disallowed CORS headers"


@pytest.mark.asyncio
async def test_preflight_allows_request_origin_if_origins_wildcard_and_credentials_allowed():
    client = ASGITestClient(
        get_middleware_app(
            ASGIMiddlewareCORS,
            allow_origins=["*"],
            allow_methods=["POST"],
            allow_credentials=True,
        )
    )

    # Test pre-flight response
    headers = {
        b"origin": b"https://example.org",
        b"access-control-request-method": b"POST",
    }
    response = await client.options("/", headers=headers)
    assert response.status_code == 200
    assert response.headers[b"access-control-allow-origin"] == b"https://example.org"
    assert response.headers[b"access-control-allow-credentials"] == b"true"
    assert response.headers[b"vary"] == b"Origin"


@pytest.mark.asyncio
async def test_cors_preflight_allow_all_methods():
    client = ASGITestClient(
        get_middleware_app(ASGIMiddlewareCORS, allow_origins=["*"], allow_methods=["*"])
    )

    headers = {
        b"origin": b"https://example.org",
        b"access-control-request-method": b"POST",
    }

    for method in (b"DELETE", b"GET", b"HEAD", b"OPTIONS", b"PATCH", b"POST", b"PUT"):
        response = await client.options("/", headers=headers)
        assert response.status_code == 200
        assert method in response.headers[b"access-control-allow-methods"]


# @pytest.mark.asyncio
# async def test_cors_allow_all_methods():
#     def homepage(request):
#         return PlainTextResponse("Hello, World!", status_code=200)
#
#     app = Starlette(
#         routes=[
#             Route(
#                 "/",
#                 endpoint=homepage,
#                 methods=["delete", "get", "head", "options", "patch", "post", "put"],
#             )
#         ],
#         middleware=[
#             Middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"])
#         ],
#     )
#
#     client = test_client_factory(app)
#
#     headers = {"Origin": "https://example.org"}
#
#     for method in ("delete", "get", "head", "options", "patch", "post", "put"):
#         response = getattr(client, method)("/", headers=headers, json={})
#         assert response.status_code == 200


@pytest.mark.asyncio
async def test_cors_allow_origin_regex():
    client = ASGITestClient(
        get_middleware_app(
            ASGIMiddlewareCORS,
            allow_headers=["X-Example", "Content-Type"],
            allow_origin_regex=r"^https://.*",
            allow_credentials=True,
        )
    )

    # Test standard response
    headers = {b"origin": b"https://example.org"}
    response = await client.get("/", headers=headers)
    assert response.status_code == 200
    assert response.text == "Hello, World!"
    assert response.headers[b"access-control-allow-origin"] == b"https://example.org"
    assert response.headers[b"access-control-allow-credentials"] == b"true"

    # Test standard credentialed response
    headers = {b"origin": b"https://example.org", b"cookie": b"star_cookie=sugar"}
    response = await client.get("/", headers=headers)
    assert response.status_code == 200
    assert response.text == "Hello, World!"
    assert response.headers[b"access-control-allow-origin"] == b"https://example.org"
    assert response.headers[b"access-control-allow-credentials"] == b"true"

    # Test disallowed standard response
    # Note that enforcement is a browser concern. The disallowed-ness is reflected
    # in the lack of an "access-control-allow-origin" header in the response.
    headers = {b"origin": b"http://example.org"}
    response = await client.get("/", headers=headers)
    assert response.status_code == 200
    assert response.text == "Hello, World!"
    assert b"access-control-allow-origin" not in response.headers

    # Test pre-flight response
    headers = {
        b"origin": b"https://another.com",
        b"access-control-request-method": b"GET",
        b"access-control-request-headers": b"X-Example, content-type",
    }
    response = await client.options("/", headers=headers)
    assert response.status_code == 200
    assert response.text == "OK"
    assert response.headers[b"access-control-allow-origin"] == b"https://another.com"
    assert response.headers[b"access-control-allow-headers"] == (
        b"accept, accept-language, content-language, content-type, x-example"
    )
    assert response.headers[b"access-control-allow-credentials"] == b"true"

    # Test disallowed pre-flight response
    headers = {
        b"origin": b"http://another.com",
        b"access-control-request-method": b"GET",
        b"access-control-request-headers": b"X-Example",
    }
    response = await client.options("/", headers=headers)
    assert response.status_code == 400
    assert response.text == "Disallowed CORS origin"
    assert b"access-control-allow-origin" not in response.headers


@pytest.mark.asyncio
async def test_cors_allow_origin_regex_full_match():
    client = ASGITestClient(
        get_middleware_app(
            ASGIMiddlewareCORS,
            allow_headers=["X-Example", "Content-Type"],
            allow_origin_regex=r"^https://.*\.example\.org$",
        )
    )

    # Test standard response
    headers = {b"origin": b"https://subdomain.example.org"}
    response = await client.get("/", headers=headers)
    assert response.status_code == 200
    assert response.text == "Hello, World!"
    assert (
        response.headers[b"access-control-allow-origin"]
        == b"https://subdomain.example.org"
    )
    assert "access-control-allow-credentials" not in response.headers

    # Test diallowed standard response
    headers = {b"origin": b"https://subdomain.example.org.hacker.com"}
    response = await client.get("/", headers=headers)
    assert response.status_code == 200
    assert response.text == "Hello, World!"
    assert b"access-control-allow-origin" not in response.headers


@pytest.mark.asyncio
async def test_cors_credentialed_requests_return_specific_origin():
    client = ASGITestClient(get_middleware_app(ASGIMiddlewareCORS, allow_origins=["*"]))

    # Test credentialed request
    headers = {b"origin": b"https://example.org", b"Cookie": b"star_cookie=sugar"}
    response = await client.get("/", headers=headers)
    ic(response.headers)
    assert response.status_code == 200
    assert response.text == "Hello, World!"
    assert response.headers[b"access-control-allow-origin"] == b"https://example.org"
    assert b"access-control-allow-credentials" not in response.headers


@pytest.mark.asyncio
async def test_cors_vary_header_defaults_to_origin():
    client = ASGITestClient(
        get_middleware_app(ASGIMiddlewareCORS, allow_origins=["https://example.org"])
    )

    headers = {b"origin": b"https://example.org"}

    # client = test_client_factory(app)

    response = await client.get("/", headers=headers)
    assert response.status_code == 200
    assert response.headers[b"vary"] == b"Origin"


@pytest.mark.asyncio
async def test_cors_vary_header_is_not_set_for_non_credentialed_request():
    client = ASGITestClient(
        get_middleware_app(
            ASGIMiddlewareCORS,
            allow_origins=["https://example.org"],
            app_response_header={"Vary": "Accept-Encoding"},
        )
    )

    response = await client.get("/", headers={b"origin": b"https://someplace.org"})
    assert response.status_code == 200
    assert response.headers[b"vary"] == b"Accept-Encoding"


@pytest.mark.asyncio
async def test_cors_vary_header_is_properly_set_for_credentialed_request():
    client = ASGITestClient(
        get_middleware_app(
            ASGIMiddlewareCORS,
            allow_origins=["*"],
            app_response_header={"vary": "Accept-Encoding"},
        )
    )

    response = await client.get(
        "/", headers={b"cookie": b"foo=bar", b"origin": b"https://someplace.org"}
    )
    assert response.status_code == 200
    assert response.headers[b"vary"] == b"Accept-Encoding, Origin"


@pytest.mark.asyncio
async def test_cors_vary_header_is_properly_set_when_allow_origins_is_not_wildcard():
    client = ASGITestClient(
        get_middleware_app(
            ASGIMiddlewareCORS,
            allow_origins=["https://example.org"],
            app_response_header={"vary": "Accept-Encoding"},
        )
    )

    response = await client.get("/", headers={b"origin": b"https://example.org"})
    assert response.status_code == 200
    assert response.headers[b"vary"] == b"Accept-Encoding, Origin"


@pytest.mark.asyncio
async def test_cors_allowed_origin_does_not_leak_between_credentialed_requests():
    client = ASGITestClient(
        get_middleware_app(
            ASGIMiddlewareCORS,
            allow_origins=["*"],
            allow_headers=["*"],
            allow_methods=["*"],
        )
    )

    response = await client.get("/", headers={b"origin": b"https://someplace.org"})
    assert response.headers[b"access-control-allow-origin"] == b"*"
    assert b"access-control-allow-credentials" not in response.headers

    response = await client.get(
        "/", headers={b"cookie": b"foo=bar", b"origin": b"https://someplace.org"}
    )
    assert response.headers[b"access-control-allow-origin"] == b"https://someplace.org"
    assert b"access-control-allow-credentials" not in response.headers

    response = await client.get("/", headers={b"origin": b"https://someplace.org"})
    assert response.headers[b"access-control-allow-origin"] == b"*"
    assert b"access-control-allow-credentials" not in response.headers
