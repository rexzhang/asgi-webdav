import pytest
from icecream import ic

from asgi_webdav.middleware.cors import ASGIMiddlewareCORS

from .asgi_test_kit import ASGIApp, ASGITestClient


def get_middleware_app(middleware, **kwargs):
    if "app_response_header" in kwargs:
        return middleware(
            ASGIApp(app_response_header=kwargs.pop("app_response_header")), **kwargs
        )
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
        "Origin": "https://example.org",
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "X-Example",
    }
    response = await client.options("/", headers=headers)
    assert response.status_code == 200
    assert response.text == "OK"
    assert response.headers["access-control-allow-origin"] == "https://example.org"
    assert response.headers["access-control-allow-headers"] == "X-Example"
    assert response.headers["access-control-allow-credentials"] == "true"
    assert response.headers["vary"] == "Origin"

    # Test standard response
    headers = {"Origin": "https://example.org"}
    response = await client.get("/", headers=headers)
    ic("in test", response)
    assert response.status_code == 200
    assert response.text == "Hello, World!"
    assert response.headers["access-control-allow-origin"] == "*"
    assert response.headers["access-control-expose-headers"] == "X-Status"
    assert response.headers["access-control-allow-credentials"] == "true"

    # Test standard credentialed response
    headers = {"Origin": "https://example.org", "Cookie": "star_cookie=sugar"}
    response = await client.get("/", headers=headers)
    ic("in test", response)
    assert response.status_code == 200
    assert response.text == "Hello, World!"
    assert response.headers["access-control-allow-origin"] == "https://example.org"
    assert response.headers["access-control-expose-headers"] == "X-Status"
    assert response.headers["access-control-allow-credentials"] == "true"

    # Test non-CORS response
    response = await client.get("/")
    assert response.status_code == 200
    assert response.text == "Hello, World!"
    assert "access-control-allow-origin" not in response.headers


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
        "Origin": "https://example.org",
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "X-Example",
    }
    response = await client.options("/", headers=headers)
    assert response.status_code == 200
    assert response.text == "OK"
    assert response.headers["access-control-allow-origin"] == "*"
    assert response.headers["access-control-allow-headers"] == "X-Example"
    assert "access-control-allow-credentials" not in response.headers
    assert "vary" not in response.headers

    # Test standard response
    headers = {"Origin": "https://example.org"}
    response = await client.get("/", headers=headers)
    assert response.status_code == 200
    assert response.text == "Hello, World!"
    assert response.headers["access-control-allow-origin"] == "*"
    assert response.headers["access-control-expose-headers"] == "X-Status"
    assert "access-control-allow-credentials" not in response.headers

    # Test non-CORS response
    response = await client.get("/")
    assert response.status_code == 200
    assert response.text == "Hello, World!"
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.asyncio
async def test_cors_allow_url_regex():
    headers = {
        "Origin": "https://example.org",
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "X-Example",
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
    assert "access-control-allow-origin" not in response.headers

    response = await client.get("/cors_path", headers=headers)
    assert response.status_code == 200
    assert response.text == "Hello, World!"
    assert "access-control-allow-origin" in response.headers
    response = await client.get("/cors_path/", headers=headers)
    assert response.status_code == 200
    assert response.text == "Hello, World!"
    assert "access-control-allow-origin" in response.headers
    response = await client.get("/cors_path/sub", headers=headers)
    assert response.status_code == 200
    assert response.text == "Hello, World!"
    assert "access-control-allow-origin" in response.headers

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
    assert "access-control-allow-origin" not in response.headers
    response = await client.get("/cors_path/", headers=headers)
    assert response.status_code == 200
    assert response.text == "Hello, World!"
    assert "access-control-allow-origin" in response.headers
    response = await client.get("/cors_path/sub", headers=headers)
    assert response.status_code == 200
    assert response.text == "Hello, World!"
    assert "access-control-allow-origin" in response.headers


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
        "Origin": "https://example.org",
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "X-Example, Content-Type",
    }
    response = await client.options("/", headers=headers)
    assert response.status_code == 200
    assert response.text == "OK"
    assert response.headers["access-control-allow-origin"] == "https://example.org"
    assert response.headers["access-control-allow-headers"] == (
        "Accept, Accept-Language, Content-Language, Content-Type, X-Example"
    )
    assert "access-control-allow-credentials" not in response.headers

    # Test standard response
    headers = {"Origin": "https://example.org"}
    response = await client.get("/", headers=headers)
    assert response.status_code == 200
    assert response.text == "Hello, World!"
    assert response.headers["access-control-allow-origin"] == "https://example.org"
    assert "access-control-allow-credentials" not in response.headers

    # Test non-CORS response
    response = await client.get("/")
    assert response.status_code == 200
    assert response.text == "Hello, World!"
    assert "access-control-allow-origin" not in response.headers


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
        "Origin": "https://another.org",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "X-Nope",
    }
    response = await client.options("/", headers=headers)
    assert response.status_code == 400
    assert response.text == "Disallowed CORS origin, method, headers"
    assert "access-control-allow-origin" not in response.headers

    # Bug specific test, https://github.com/encode/starlette/pull/1199
    # Test preflight response text with multiple disallowed headers
    headers = {
        "Origin": "https://example.org",
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "X-Nope-1, X-Nope-2",
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
        "Origin": "https://example.org",
        "Access-Control-Request-Method": "POST",
    }
    response = await client.options(
        "/",
        headers=headers,
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://example.org"
    assert response.headers["access-control-allow-credentials"] == "true"
    assert response.headers["vary"] == "Origin"


@pytest.mark.asyncio
async def test_cors_preflight_allow_all_methods():
    client = ASGITestClient(
        get_middleware_app(ASGIMiddlewareCORS, allow_origins=["*"], allow_methods=["*"])
    )

    headers = {
        "Origin": "https://example.org",
        "Access-Control-Request-Method": "POST",
    }

    for method in ("DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"):
        response = await client.options("/", headers=headers)
        assert response.status_code == 200
        assert method in response.headers["access-control-allow-methods"]


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
            allow_origin_regex="^https://.*",
            allow_credentials=True,
        )
    )

    # Test standard response
    headers = {"Origin": "https://example.org"}
    response = await client.get("/", headers=headers)
    assert response.status_code == 200
    assert response.text == "Hello, World!"
    assert response.headers["access-control-allow-origin"] == "https://example.org"
    assert response.headers["access-control-allow-credentials"] == "true"

    # Test standard credentialed response
    headers = {"Origin": "https://example.org", "Cookie": "star_cookie=sugar"}
    response = await client.get("/", headers=headers)
    assert response.status_code == 200
    assert response.text == "Hello, World!"
    assert response.headers["access-control-allow-origin"] == "https://example.org"
    assert response.headers["access-control-allow-credentials"] == "true"

    # Test disallowed standard response
    # Note that enforcement is a browser concern. The disallowed-ness is reflected
    # in the lack of an "access-control-allow-origin" header in the response.
    headers = {"Origin": "http://example.org"}
    response = await client.get("/", headers=headers)
    assert response.status_code == 200
    assert response.text == "Hello, World!"
    assert "access-control-allow-origin" not in response.headers

    # Test pre-flight response
    headers = {
        "Origin": "https://another.com",
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "X-Example, content-type",
    }
    response = await client.options("/", headers=headers)
    assert response.status_code == 200
    assert response.text == "OK"
    assert response.headers["access-control-allow-origin"] == "https://another.com"
    assert response.headers["access-control-allow-headers"] == (
        "Accept, Accept-Language, Content-Language, Content-Type, X-Example"
    )
    assert response.headers["access-control-allow-credentials"] == "true"

    # Test disallowed pre-flight response
    headers = {
        "Origin": "http://another.com",
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "X-Example",
    }
    response = await client.options("/", headers=headers)
    assert response.status_code == 400
    assert response.text == "Disallowed CORS origin"
    assert "access-control-allow-origin" not in response.headers


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
    headers = {"Origin": "https://subdomain.example.org"}
    response = await client.get("/", headers=headers)
    assert response.status_code == 200
    assert response.text == "Hello, World!"
    assert (
        response.headers["access-control-allow-origin"]
        == "https://subdomain.example.org"
    )
    assert "access-control-allow-credentials" not in response.headers

    # Test diallowed standard response
    headers = {"Origin": "https://subdomain.example.org.hacker.com"}
    response = await client.get("/", headers=headers)
    assert response.status_code == 200
    assert response.text == "Hello, World!"
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.asyncio
async def test_cors_credentialed_requests_return_specific_origin():
    client = ASGITestClient(get_middleware_app(ASGIMiddlewareCORS, allow_origins=["*"]))

    # Test credentialed request
    headers = {"Origin": "https://example.org", "Cookie": "star_cookie=sugar"}
    response = await client.get("/", headers=headers)
    assert response.status_code == 200
    assert response.text == "Hello, World!"
    assert response.headers["access-control-allow-origin"] == "https://example.org"
    assert "access-control-allow-credentials" not in response.headers


@pytest.mark.asyncio
async def test_cors_vary_header_defaults_to_origin():
    client = ASGITestClient(
        get_middleware_app(ASGIMiddlewareCORS, allow_origins=["https://example.org"])
    )

    headers = {"Origin": "https://example.org"}

    # client = test_client_factory(app)

    response = await client.get("/", headers=headers)
    assert response.status_code == 200
    assert response.headers["vary"] == "Origin"


@pytest.mark.asyncio
async def test_cors_vary_header_is_not_set_for_non_credentialed_request():
    client = ASGITestClient(
        get_middleware_app(
            ASGIMiddlewareCORS,
            allow_origins=["https://example.org"],
            app_response_header={"Vary": "Accept-Encoding"},
        )
    )

    response = await client.get("/", headers={"Origin": "https://someplace.org"})
    assert response.status_code == 200
    assert response.headers["vary"] == "Accept-Encoding"


@pytest.mark.asyncio
async def test_cors_vary_header_is_properly_set_for_credentialed_request():
    client = ASGITestClient(
        get_middleware_app(
            ASGIMiddlewareCORS,
            allow_origins=["*"],
            app_response_header={"Vary": "Accept-Encoding"},
        )
    )

    response = await client.get(
        "/", headers={"Cookie": "foo=bar", "Origin": "https://someplace.org"}
    )
    assert response.status_code == 200
    assert response.headers["vary"] == "Accept-Encoding, Origin"


@pytest.mark.asyncio
async def test_cors_vary_header_is_properly_set_when_allow_origins_is_not_wildcard():
    client = ASGITestClient(
        get_middleware_app(
            ASGIMiddlewareCORS,
            allow_origins=["https://example.org"],
            app_response_header={"Vary": "Accept-Encoding"},
        )
    )

    response = await client.get("/", headers={"Origin": "https://example.org"})
    assert response.status_code == 200
    assert response.headers["vary"] == "Accept-Encoding, Origin"


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

    response = await client.get("/", headers={"Origin": "https://someplace.org"})
    assert response.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in response.headers

    response = await client.get(
        "/", headers={"Cookie": "foo=bar", "Origin": "https://someplace.org"}
    )
    assert response.headers["access-control-allow-origin"] == "https://someplace.org"
    assert "access-control-allow-credentials" not in response.headers

    response = await client.get("/", headers={"Origin": "https://someplace.org"})
    assert response.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in response.headers
