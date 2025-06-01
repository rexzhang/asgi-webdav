from asgi_webdav.config import Config
from asgi_webdav.constants import DAVPath
from asgi_webdav.provider.webhdfs import WebHDFSProvider


def test_get_url():
    root = WebHDFSProvider(
        config=Config(),
        prefix=DAVPath(""),
        uri="http://my_domain.com:9870/webhdfs/v1",
        home_dir=True,
    )
    url = root._get_url_path(path=DAVPath("/new_folder/file.txt"), user_name=None)
    user_url = root._get_url_path(path=DAVPath("/new_folder/file.txt"), user_name="me")
    url_2 = root._get_url_path(path=DAVPath("/new_folder/file#1.txt"), user_name=None)
    user_url_2 = root._get_url_path(
        path=DAVPath("/new_folder/file#1.txt"), user_name="me"
    )
    assert url == DAVPath("/new_folder/file.txt")
    assert user_url == DAVPath("/user/me/new_folder/file.txt")
    assert url_2 == DAVPath("/new_folder/file%231.txt")
    assert user_url_2 == DAVPath("/user/me/new_folder/file%231.txt")
    root_2 = WebHDFSProvider(
        config=Config(), prefix=DAVPath(""), uri="http://my_domain.com:9870/webhdfs/v1"
    )
    url_3 = root_2._get_url_path(path=DAVPath("/new_folder/file.txt"), user_name=None)
    user_url_3 = root_2._get_url_path(
        path=DAVPath("/new_folder/file.txt"), user_name="me"
    )
    url_4 = root_2._get_url_path(path=DAVPath("/new_folder/file#1.txt"), user_name=None)
    user_url_4 = root_2._get_url_path(
        path=DAVPath("/new_folder/file#1.txt"), user_name="me"
    )
    assert url_3 == DAVPath("/new_folder/file.txt")
    assert user_url_3 == DAVPath("/new_folder/file.txt")
    assert url_4 == DAVPath("/new_folder/file%231.txt")
    assert user_url_4 == DAVPath("/new_folder/file%231.txt")
