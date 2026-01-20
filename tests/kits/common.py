import itertools
import random
from pathlib import Path

from asgi_webdav.constants import (
    DEFAULT_COMPRESSION_CONTENT_MINIMUM_LENGTH,
    DAVResponseBodyGenerator,
)

CLIENT_UA_FIREFOX = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:107.0) Gecko/20100101 Firefox/107.0"
CLIENT_UA_SAFARI = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.1 Safari/605.1.15"
CLIENT_UA_CHROME = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36"

CLIENT_UA_MACOS_FINDER = "WebDAVFS/3.0.0 (03008000) Darwin/21.3.0 (x86_64)"
CLIENT_UA_WINDOWS_EXPLORER = "Microsoft-WebDAV-MiniRedir/10.0.19043"


def get_project_root_path() -> Path:
    return Path(__file__).parent.parent.parent


def get_bytes(length: int = DEFAULT_COMPRESSION_CONTENT_MINIMUM_LENGTH) -> bytes:
    return b"b0" * length


async def get_all_data_from_response_body_generator(
    body_generator: DAVResponseBodyGenerator,
) -> bytes:

    result = b""
    async for data, more_body in body_generator:
        result += data

    return result


def get_generate_random_bytes(length):
    random_gen = (random.randint(0, 255) for _ in iter(int, 1))
    selected_bytes = itertools.islice(random_gen, length)

    return bytes(selected_bytes)
