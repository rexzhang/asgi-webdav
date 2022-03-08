from pathlib import Path

import pytest

from asgi_webdav.provider.file_system import (
    _load_extra_property,
    _update_extra_property,
)

DAV_FILENAME = "/tmp/test.DAV"


@pytest.mark.asyncio
async def test_property_file():
    dav_file = Path(DAV_FILENAME)
    patches_data_1 = [(("ns1", "key1"), "v1", True)]
    patches_data_2 = [(("ns2", "key2"), "v2", True)]
    patches_data_3 = [(("ns2", "key2"), "v2", False)]

    if dav_file.exists():
        dav_file.unlink()

    assert await _update_extra_property(Path(DAV_FILENAME), patches_data_1)
    assert len(await _load_extra_property(dav_file)) == 1

    assert await _update_extra_property(Path(DAV_FILENAME), patches_data_2)
    assert len(await _load_extra_property(dav_file)) == 2

    assert await _update_extra_property(Path(DAV_FILENAME), patches_data_3)
    assert len(await _load_extra_property(dav_file)) == 1
