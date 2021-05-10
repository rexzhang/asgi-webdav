from asgi_webdav.helpers import guess_type


def test_guess_type():
    content_type, encoding = guess_type("README")
    assert isinstance(content_type, str)

    content_type, encoding = guess_type("test.md")
    assert isinstance(content_type, str)

    content_type, encoding = guess_type("./../BuildDocker.sh")
    assert isinstance(content_type, str)
