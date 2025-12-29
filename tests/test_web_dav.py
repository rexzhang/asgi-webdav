import pytest

from asgi_webdav.config import Provider
from asgi_webdav.exceptions import DAVExceptionProviderInitFailed
from asgi_webdav.provider.file_system import FileSystemProvider
from asgi_webdav.provider.memory import MemoryProvider
from asgi_webdav.provider.webhdfs import WebHDFSProvider
from asgi_webdav.web_dav import WebDAV


def test_match_provider_class():
    assert (
        WebDAV.match_provider_class(Provider("/fs", "file:///tmp"))
        == FileSystemProvider
    )
    assert (
        WebDAV.match_provider_class(Provider("/memory", "memory:///")) == MemoryProvider
    )

    with pytest.raises(DAVExceptionProviderInitFailed):
        WebDAV.match_provider_class(Provider("/wrong_provider", "wrong_provider:///"))

    assert (
        WebDAV.match_provider_class(
            Provider("/webhdfs", "http://localhost:9870/webhdfs/v1", type="webhdfs")
        )
        == WebHDFSProvider
    )

    with pytest.raises(DAVExceptionProviderInitFailed):
        WebDAV.match_provider_class(
            Provider(
                "/wrong_http_provider",
                "http://localhost:9870/webhdfs/v1",
                type="wrong_http_provider",
            )
        )
