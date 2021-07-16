from asgi_webdav.config import update_config_from_obj, get_config
from asgi_webdav.web_dav import WebDAV


config_data = {
    "provider_mapping": [
        {
            "prefix": "/",
            "uri": "file://.",
        },
    ],
}


def test():
    update_config_from_obj(config_data)
    webdav = WebDAV(get_config())

    # macOS
    assert webdav.is_ignore_in_dir_browser(".DS_Store")
    assert webdav.is_ignore_in_dir_browser("._.test")

    # Windows
    assert webdav.is_ignore_in_dir_browser("Thumbs.db")

    # Synology
    assert webdav.is_ignore_in_dir_browser("#recycle")
    assert webdav.is_ignore_in_dir_browser("@eaDir")
