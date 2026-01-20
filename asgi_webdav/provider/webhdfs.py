# mypy: ignore-errors

from __future__ import annotations

import hashlib
from logging import getLogger
from typing import TypedDict
from urllib.parse import quote, urlencode

try:
    import httpx
    from httpx_kerberos import HTTPKerberosAuth  # type: ignore
except ImportError:
    httpx = None
    HTTPKerberosAuth = None

from asgi_webdav.constants import (
    DAVDepth,
    DAVPath,
    DAVPropertyIdentity,
    DAVRangeType,
    DAVResponseBodyGenerator,
    DAVResponseContentRange,
    DAVTime,
)
from asgi_webdav.exceptions import DAVExceptionProviderInitFailed
from asgi_webdav.helpers import guess_type
from asgi_webdav.property import DAVProperty, DAVPropertyBasicData
from asgi_webdav.provider.common import (
    DAVProvider,
    DAVProviderFeature,
    get_response_content_range,
)
from asgi_webdav.request import DAVRequest

logger = getLogger(__name__)


class FileStatus(TypedDict):
    fileId: int
    length: int
    modificationTime: int
    type: str


class WebHDFSProvider(DAVProvider):
    type = "webhdfs"
    feature = DAVProviderFeature(
        content_range=True,
        home_dir=True,
    )

    def __init__(self, *args, **kwargs):
        if httpx is None or HTTPKerberosAuth is None:
            raise DAVExceptionProviderInitFailed(
                "httpx and httpx_kerberos are required for WebHDFSProvider, please check your installation"
            )

        super().__init__(*args, **kwargs)
        self.uri = self.uri.rstrip("/")
        self.client = httpx.AsyncClient(auth=HTTPKerberosAuth())

    def __repr__(self):
        return self.uri

    def _get_url_path(self, path: DAVPath, user_name: str | None) -> DAVPath:
        """Prepend the requested path with the home directory (if needed)."""
        if self.home_dir and user_name:
            return DAVPath(quote(f"/user/{user_name}")).add_child(
                quote(str(path), safe="/")
            )
        return DAVPath(quote(str(path), safe="/"))

    async def _get_dav_property_d1_infinity(
        self,
        dav_properties: dict[DAVPath, DAVProperty],
        request: DAVRequest,
        url_path: DAVPath,
        infinity: bool,
        depth_limit: int = 99,
    ):
        # TODO: Add support for infinity depth
        if infinity:
            raise NotImplementedError

        actual_url = self.uri + f"{url_path}?op=LISTSTATUS&doAs={request.user.username}"

        try:
            response = await self.client.get(actual_url)
            response.raise_for_status()
            data = response.json()

        except httpx.HTTPStatusError:
            logger.exception("Exception in get dav property d1 infinity.")
            return

        for file_status in data["FileStatuses"]["FileStatus"]:
            sub_path = url_path.add_child(file_status.get("pathSuffix"))

            dav_properties[sub_path] = await self._create_dav_property_obj(
                request, sub_path, file_status
            )

        return

    async def _get_dav_property_d0(
        self,
        request: DAVRequest,
        url_path: DAVPath,
    ) -> tuple[int, DAVProperty]:
        status_code, file_status = await self._do_filestatus(request, url_path)
        return status_code, await self._create_dav_property_obj(
            request, url_path, file_status
        )

    async def _do_filestatus(
        self, request: DAVRequest, url_path: DAVPath
    ) -> tuple[int, FileStatus]:
        actual_url = (
            self.uri + f"{url_path}?op=GETFILESTATUS&doAs={request.user.username}"
        )
        response = await self.client.get(actual_url)
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
                content_length=file_status.get("length", 0),
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
        dav_properties: dict[DAVPath, DAVProperty] = dict()

        url_path = self._get_url_path(request.dist_src_path, request.user.username)
        try:
            status_code, dav_property = await self._get_dav_property_d0(
                request, url_path
            )

            dav_properties[request.src_path] = dav_property

            if (
                request.depth != DAVDepth.ZERO
                and dav_properties[request.src_path].is_collection
            ):
                # is not d0 and is dir
                await self._get_dav_property_d1_infinity(
                    dav_properties=dav_properties,
                    request=request,
                    url_path=url_path,
                    infinity=request.depth == DAVDepth.INFINITY,
                )

            return dav_properties

        except httpx.HTTPStatusError:
            return dav_properties

    async def _do_proppatch(self, request: DAVRequest) -> int:
        # WebDAV does not natively support the access time property, but HDFS does.
        # Since WebDAV clients cannot provide an access time, we set HDFS access time to match the modification time.

        # WebDAV does not include a 'group' property as part of its standard properties.
        # WebDAV does not expose the ability to modify 'owner'

        # HDFS does not support creation time, while WebDAV does.
        # WebDAV allows setting the creation time as a separate property,
        # but this information is unavailable or unsupported in HDFS.

        # Permissions are managed through the 'acl' property, which is part of the WebDAV ACL extension.
        # The 'acl' property is not supported in this implementation.

        parent_exists, file_exists, is_collection = await self._precheck_source(request)
        if not file_exists:
            return 404

        return 207

    async def _do_mkcol(self, request: DAVRequest) -> int:
        parent_exists, dir_exists, _ = await self._precheck_source(request)
        url_path = self._get_url_path(request.dist_src_path, request.user.username)
        actual_url = self.uri + f"{url_path}?op=MKDIRS&doAs={request.user.username}"
        if not parent_exists:
            return 409
        if dir_exists:
            return 405
        if request.body_is_parsed_success and await request.receive():
            return 415

        try:
            response = await self.client.put(actual_url)
            response.raise_for_status()
            return 201

        except httpx.HTTPStatusError as error:
            return error.response.status_code

    async def _do_get(self, request: DAVRequest) -> tuple[
        int,
        DAVPropertyBasicData | None,
        DAVResponseBodyGenerator | None,
        DAVResponseContentRange | None,
    ]:
        url_path = self._get_url_path(request.dist_src_path, request.user.username)
        try:
            status_response, dav_property = await self._get_dav_property_d0(
                request, url_path
            )
            if dav_property.is_collection:
                return status_response, dav_property.basic_data, None, None

            # Read file's content
            response_content_range = get_response_content_range(
                request_ranges=request.ranges,
                file_size=dav_property.basic_data.content_length,
            )
            if response_content_range is None:
                response_content_range = DAVResponseContentRange(
                    DAVRangeType.RANGE,
                    0,
                    dav_property.basic_data.content_length - 1,
                    dav_property.basic_data.content_length,
                )
                status_response = 200
            else:
                status_response = 206

            body_generator = self._dav_response_data_generator(
                request,
                url_path,
                response_content_range.content_start,
                response_content_range.content_end,
            )
            return (
                status_response,
                dav_property.basic_data,
                body_generator,
                response_content_range,
            )

        except httpx.HTTPStatusError as error:
            return error.response.status_code, None, None, None

    async def _dav_response_data_generator(
        self,
        request: DAVRequest,
        url_path: DAVPath,
        content_range_start: int | None = None,
        content_range_end: int | None = None,
    ) -> DAVResponseBodyGenerator:
        actual_url = self.uri + f"{url_path}?op=OPEN&doAs={request.user.username}"

        if content_range_start:
            actual_url += f"&offset={content_range_start}"
            if content_range_end:
                actual_url += f"&length={content_range_end - content_range_start + 1}"
        elif content_range_end:
            actual_url += f"&length={content_range_end + 1}"

        async with self.client.stream(
            "GET", actual_url, follow_redirects=True
        ) as response:
            response.raise_for_status()
            previous_chunk = None
            async for chunk in response.aiter_bytes():
                if not previous_chunk:
                    previous_chunk = chunk
                    continue
                yield previous_chunk, True
                previous_chunk = chunk

            yield previous_chunk, False

    async def _do_head(
        self, request: DAVRequest
    ) -> tuple[int, DAVPropertyBasicData | None]:
        url_path = self._get_url_path(request.dist_src_path, request.user.username)
        try:
            status_response, dav_property = await self._get_dav_property_d0(
                request, url_path
            )
            return 200, dav_property.basic_data

        except httpx.HTTPStatusError as error:
            return error.response.status_code, None

    async def _do_delete(self, request: DAVRequest) -> int:
        parent_exists, file_exists, is_collection = await self._precheck_source(request)
        if not file_exists:
            return 404

        url_path = self._get_url_path(request.dist_src_path, request.user.username)
        actual_url = (
            self.uri
            + f"{url_path}?op=DELETE&recursive=true&doAs={request.user.username}"
        )
        try:
            response = await self.client.delete(actual_url)
            response.raise_for_status()
            return 204

        except httpx.HTTPStatusError:
            return 424

    async def _do_put(self, request: DAVRequest) -> int:
        parent_exists, file_exists, _ = await self._precheck_source(request)
        if not parent_exists:
            return 409

        url_path = self._get_url_path(request.dist_src_path, request.user.username)
        actual_url = (
            self.uri
            + f"{url_path}?op=CREATE&overwrite=true&doAs={request.user.username}"
        )  # PUT requests are always overwriting.
        try:
            # WebHDFS redirects on PUT
            response = await self.client.put(actual_url)
            if response.status_code != 307:
                response.raise_for_status()

            location = response.headers["location"]

            # The data should be sent in the second request
            # Location path already includes the required parameters
            response = await self.client.put(location, content=_stream_body(request))
            response.raise_for_status()
            if file_exists:
                return 204
            return 201

        except httpx.HTTPStatusError as error:
            return error.response.status_code

    async def _get_res_etag(self, request: DAVRequest) -> str:
        url_path = self._get_url_path(request.dist_src_path, request.user.username)

        status_code, file_status = await self._do_filestatus(request, url_path)
        return 'W/"{}"'.format(
            hashlib.md5(
                f"{file_status['fileId']}{file_status['modificationTime']}".encode()
            ).hexdigest()
        )

    async def _do_copy(self, request: DAVRequest) -> int:
        # TODO: Should not overwrite if header "Overwrite: F" is specified.
        raise NotImplementedError

    async def _do_move(self, request: DAVRequest) -> int:
        parent_exists, equal_paths, file_exists = await self._precheck_destination(
            request
        )
        if equal_paths:
            return 403
        if not parent_exists:
            return 409
        if file_exists and not request.overwrite:
            # Should not overwrite if header "Overwrite: F" is specified.
            return 412
        if file_exists:
            # Delete existing file, we will overwrite
            url_path = self._get_url_path(request.dist_dst_path, request.user.username)
            actual_url = self.uri + f"{url_path}?op=DELETE&recursive=true"
            try:
                response = await self.client.delete(actual_url)
                response.raise_for_status()
            except httpx.HTTPStatusError:
                # Not able to overwrite
                return 403

        src_path = self._get_url_path(request.dist_src_path, request.user.username)
        dst_path = self._get_url_path(request.dist_dst_path, request.user.username)
        actual_url = (
            self.uri
            + f"{src_path}?op=RENAME&doAs={request.user.username}&"
            + urlencode({"destination": dst_path})
        )
        try:
            # Rename method in WebHDFS does not overwrite the existing file.
            resp = await self.client.put(actual_url)
            resp.raise_for_status()
            if file_exists:
                return 204
            return 201

        except httpx.HTTPStatusError as error:
            return error.response.status_code

    async def _precheck_source(self, request: DAVRequest) -> tuple[bool, bool, bool]:
        parent_exists = True
        file_exists = True
        try:
            parent_state, _ = await self._do_filestatus(
                request,
                self._get_url_path(request.dist_src_path.parent, request.user.username),
            )
        except httpx.HTTPStatusError:
            parent_exists = False
        try:
            status_state, file_status = await self._do_filestatus(
                request,
                self._get_url_path(request.dist_src_path, request.user.username),
            )
            is_collection = file_status.get("type") == "DIRECTORY"
        except httpx.HTTPStatusError:
            is_collection = False
            file_exists = False
        return parent_exists, file_exists, is_collection

    async def _precheck_destination(
        self, request: DAVRequest
    ) -> tuple[bool, bool, bool]:
        parent_exists = True
        file_exists = True
        try:
            parent_state, _ = await self._do_filestatus(
                request,
                self._get_url_path(request.dist_dst_path.parent, request.user.username),
            )
        except httpx.HTTPStatusError:
            parent_exists = False
        if not parent_exists:
            return False, False, False
        equal_paths: bool = (
            request.dist_dst_path and request.dist_dst_path == request.dist_src_path
        )
        try:
            status_state, _ = await self._do_filestatus(
                request,
                self._get_url_path(request.dist_dst_path, request.user.username),
            )
        except httpx.HTTPStatusError:
            file_exists = False
        return parent_exists, equal_paths, file_exists


def _get_extra_property(file_status: FileStatus) -> dict[DAVPropertyIdentity, str]:
    return {}


async def _stream_body(request: DAVRequest):
    more_body = True
    while more_body:
        request_data = await request.receive()
        more_body = request_data.get("more_body")
        yield request_data.get("body", b"")
