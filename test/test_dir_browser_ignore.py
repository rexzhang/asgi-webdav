from asgi_webdav.config import update_config_from_obj
from asgi_webdav.distributor import DAVDistributor


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
    distributor = DAVDistributor()

    # macOS
    assert distributor.is_ignore_in_dir_browser(".DS_Store")
    assert distributor.is_ignore_in_dir_browser("._.test")

    # Windows
    assert distributor.is_ignore_in_dir_browser("Thumbs.db")

    # Synology
    assert distributor.is_ignore_in_dir_browser("#recycle")
    assert distributor.is_ignore_in_dir_browser("@eaDir")
