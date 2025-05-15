from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def patch_chronometer_start():
    with patch("asgi_webdav.config.Chronometer.start") as mock_start:
        yield mock_start
