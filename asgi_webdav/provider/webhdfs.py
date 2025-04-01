from collections.abc import AsyncGenerator
from logging import getLogger
from typing import TypedDict
from urllib.parse import quote

import httpx
from httpx_kerberos import HTTPKerberosAuth

from asgi_webdav.constants import (
    DAVPath,
    DAVPropertyIdentity,
    DAVTime,
)
from asgi_webdav.helpers import guess_type
from asgi_webdav.property import DAVProperty, DAVPropertyBasicData
from asgi_webdav.provider.dev_provider import DAVProvider
from asgi_webdav.request import DAVRequest

logger = getLogger(__name__)

kerberos_auth = HTTPKerberosAuth()

CHUNK_SIZE = 2**16


class FileStatus(TypedDict):
    fileId: int
    length: int
    modificationTime: int
    type: str


class WebHDFSProvider(DAVProvider):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.support_content_range = True
        self.uri = self.uri.rstrip("/")

    def __repr__(self):
        return self.uri

    def _get_url_path(self, path: DAVPath, user_name: str | None) -> DAVPath:
        """Prepend the requested path with the home directory (if needed)."""
        if self.home_dir and user_name:
            return DAVPath(quote(f"/user/{user_name}")).add_child(path)
        return path

    async def _get_dav_property_d0(
        self,
        request: DAVRequest,
        client: httpx.AsyncClient,
        url_path: DAVPath,
    ) -> tuple[int, DAVProperty]:
        status_code, file_status = await self._do_filestatus(client, url_path)
        return status_code, await self._create_dav_property_obj(
            request, url_path, file_status
        )

    async def _do_filestatus(
        self, client: httpx.AsyncClient, url_path: DAVPath
    ) -> tuple[int, FileStatus]:
        actual_url = self.uri + str(url_path)
        response = await client.get(actual_url + "?op=GETFILESTATUS")
        response.raise_for_status()
        return response.status_code, response.json()["FileStatus"]

    async def _create_dav_property_obj(
        self,
        request: DAVRequest,
        url_path: DAVPath,
        file_status: FileStatus,
    ) -> DAVProperty:
        is_collection = file_status.get("type") == "DIRECTORY"

        if is_collection:
            basic_data = DAVPropertyBasicData(
                is_collection=is_collection,
                display_name=url_path.name,
                creation_date=DAVTime(float(file_status.get("modificationTime", 0.0))),
                last_modified=DAVTime(float(file_status.get("modificationTime", 0.0))),
            )

        else:
            content_type, content_encoding = guess_type(self.config, url_path.name)
            charset = None

            basic_data = DAVPropertyBasicData(
                is_collection=is_collection,
                display_name=url_path.name,
                creation_date=DAVTime(float(file_status.get("modificationTime", 0.0))),
                last_modified=DAVTime(float(file_status.get("modificationTime", 0.0))),
                content_type=content_type,
                content_charset=charset,
                content_length=file_status.get("length"),
                content_encoding=content_encoding,
            )

        dav_property = DAVProperty(
            href_path=url_path, is_collection=is_collection, basic_data=basic_data
        )

        if request.propfind_only_fetch_basic:
            return dav_property

        # Extra properties, like: owner, group, permissions
        extra_data = _get_extra_property(file_status)
        dav_property.extra_data = extra_data

        # Define not found properties
        s = set(request.propfind_extra_keys) - set(extra_data.keys())
        dav_property.extra_not_found = list(s)

        return dav_property

    async def _do_propfind(self, request: DAVRequest) -> dict[DAVPath, DAVProperty]:
        raise NotImplementedError

    async def _do_proppatch(self, request: DAVRequest) -> int:
        raise NotImplementedError

    async def _do_mkcol(self, request: DAVRequest) -> int:
        url_path = self._get_url_path(request.dist_src_path, request.user.username)
        actual_url = self.uri + f"{url_path}?op=MKDIRS"
        try:
            async with httpx.AsyncClient(auth=kerberos_auth) as client:
                response = await client.put(actual_url)
                response.raise_for_status()
                return response.status_code

        except httpx.HTTPStatusError as error:
            return error.response.status_code

    async def _do_get(
        self, request: DAVRequest
    ) -> tuple[int, DAVPropertyBasicData | None, AsyncGenerator | None]:
        # 404, None, None
        # 200, DAVPropertyBasicData, None  # is_dir
        # 200/206, DAVPropertyBasicData, AsyncGenerator  # is_file
        #
        # self._create_get_head_response_headers()
        raise NotImplementedError

    async def _do_head(
        self, request: DAVRequest
    ) -> tuple[int, DAVPropertyBasicData | None]:
        url_path = self._get_url_path(request.dist_src_path, request.user.username)
        try:
            async with httpx.AsyncClient(auth=kerberos_auth) as client:
                status_response, dav_property = await self._get_dav_property_d0(
                    request, client, url_path
                )
                return status_response, dav_property.basic_data

        except httpx.HTTPStatusError as error:
            return error.response.status_code, None

    async def _do_delete(self, request: DAVRequest) -> int:
        url_path = self._get_url_path(request.dist_src_path, request.user.username)
        actual_url = self.uri + f"{url_path}?op=DELETE&recursive=true"
        try:
            async with httpx.AsyncClient(auth=kerberos_auth) as client:
                response = await client.delete(actual_url)
                response.raise_for_status()
                return response.status_code

        except httpx.HTTPStatusError as error:
            return error.response.status_code

    async def _do_put(self, request: DAVRequest) -> int:
        raise NotImplementedError

    async def _do_get_etag(self, request: DAVRequest) -> str:
        raise NotImplementedError

    async def _do_copy(self, request: DAVRequest) -> int:
        raise NotImplementedError

    async def _do_move(self, request: DAVRequest) -> int:
        raise NotImplementedError

def _get_extra_property(file_status: FileStatus) -> dict[DAVPropertyIdentity, str]:
    return {}
