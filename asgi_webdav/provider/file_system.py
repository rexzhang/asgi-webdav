from __future__ import annotations

import json
import os
import shutil
from contextlib import suppress
from logging import getLogger
from pathlib import Path
from stat import S_ISDIR
from typing import Any, cast
from uuid import uuid4

import aiofiles
import aiofiles.os
import aiofiles.ospath
from asgiref.typing import HTTPDisconnectEvent, HTTPRequestEvent

from asgi_webdav.constants import (
    RESPONSE_DATA_BLOCK_SIZE,
    DAVDepth,
    DAVPath,
    DAVPropertyIdentity,
    DAVPropertyPatchEntry,
    DAVResponseBodyGenerator,
    DAVResponseContentRange,
    DAVTime,
)
from asgi_webdav.exceptions import DAVExceptionProviderInitFailed
from asgi_webdav.helpers import detect_charset, generate_etag, guess_type
from asgi_webdav.property import DAVProperty, DAVPropertyBasicData
from asgi_webdav.provider.common import (
    DAVProvider,
    DAVProviderFeature,
    get_response_content_range,
)
from asgi_webdav.request import DAVRequest

logger = getLogger(__name__)

DAV_EXTENSION_INFO_FILE_EXTENSION = "WebDAV"
"""dav extension info file format: JSON
{
    'property': [
        [[namespace, key], value],
    ]
}
"""


def _parser_property_from_json(data: dict[str, Any]) -> dict[DAVPropertyIdentity, str]:
    try:
        if not isinstance(data, dict):
            raise ValueError

        props = data.get("property")
        if not isinstance(props, list):
            raise ValueError

    except ValueError:
        return dict()

    return {tuple(k): v for k, v in props}


async def _load_extra_property(file: Path) -> dict[DAVPropertyIdentity, str]:
    async with aiofiles.open(file, "r") as fp:
        tmp = await fp.read()
        try:
            data = json.loads(tmp)

        except json.JSONDecodeError as e:
            logger.warning(f"load extra property failed: {e}")
            return dict()

    return _parser_property_from_json(data)


async def _update_extra_property(
    file: Path, property_patches: list[DAVPropertyPatchEntry]
) -> bool:
    if not await aiofiles.ospath.exists(file):
        file.touch()  # TODO: aiofiles

    async with aiofiles.open(file, "r+") as fp:
        tmp = await fp.read()
        if len(tmp) == 0:
            data = dict()

        else:
            try:
                data = json.loads(tmp)

            except json.JSONDecodeError as e:
                logger.critical(f"update extra property failed: {e}")
                return False

            data = _parser_property_from_json(data)

        for sn_key, value, is_set_method in property_patches:
            if is_set_method:
                # set/update
                data[sn_key] = value
            else:
                # remove
                data.pop(sn_key, None)

        data = {"property": [tuple((tuple(k), v)) for k, v in data.items()]}
        tmp = json.dumps(data)
        await fp.seek(0)
        await fp.write(tmp)
        await fp.truncate()

    return True


async def _dav_response_body_generator(
    resource_abs_path: Path,
    content_range: DAVResponseContentRange | None = None,
    block_size: int = RESPONSE_DATA_BLOCK_SIZE,
) -> DAVResponseBodyGenerator:
    async with aiofiles.open(resource_abs_path, mode="rb") as f:
        if content_range is None:
            more_body = True
            while more_body:
                data = await f.read(block_size)
                more_body = len(data) == block_size

                yield data, more_body

        else:
            start = content_range.content_start
            end = content_range.content_end

            await f.seek(start)

            more_body = True
            while more_body:
                remain = end - start + 1

                if remain < block_size:
                    body = await f.read(remain)

                    more_body = False

                else:
                    body = await f.read(block_size)

                    more_body = True
                    start += block_size

                yield body, more_body


class FileSystemProvider(DAVProvider):
    type = "fs"
    feature = DAVProviderFeature(
        content_range=True,
        home_dir=True,
    )

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.root_path = Path(self.uri[7:])

        if not self.root_path.exists():
            raise DAVExceptionProviderInitFailed(
                'Init FileSystemProvider failed, "{}" is not exists.'.format(
                    self.root_path
                )
            )

    def __repr__(self) -> str:
        if self.home_dir:
            return f"file://{self.root_path}/{{user name}}"
        else:
            return f"file://{self.root_path}"

    def _get_fs_path(self, path: DAVPath, username: str | None) -> Path:
        if self.home_dir and username:
            return self.root_path.joinpath(username, *path.parts)

        return self.root_path.joinpath(*path.parts)

    async def _get_res_etag(self, request: DAVRequest) -> str:
        fs_path = self._get_fs_path(request.dist_src_path, request.user.username)
        stat_result = await aiofiles.os.stat(fs_path)
        return generate_etag(stat_result.st_size, stat_result.st_mtime)

    async def _get_res_etag_from_res_dist_path(
        self, res_dist_path: DAVPath, username: str | None = None
    ) -> str:
        fs_path = self._get_fs_path(res_dist_path, username)
        stat_result = await aiofiles.os.stat(fs_path)
        return generate_etag(stat_result.st_size, stat_result.st_mtime)

    @staticmethod
    def _get_fs_properties_path(path: Path) -> Path:
        return path.parent.joinpath(f"{path.name}.{DAV_EXTENSION_INFO_FILE_EXTENSION}")

    async def _create_dav_property_obj(
        self,
        request: DAVRequest,
        href_path: DAVPath,
        fs_path: Path,
        stat_result: os.stat_result,
    ) -> DAVProperty:
        is_collection = S_ISDIR(stat_result.st_mode)

        # basic
        if is_collection:
            basic_data = DAVPropertyBasicData(
                is_collection=is_collection,
                display_name=href_path.name,
                creation_date=DAVTime(stat_result.st_ctime),
                last_modified=DAVTime(stat_result.st_mtime),
            )

        else:
            content_type, content_encoding = guess_type(self.config, fs_path)
            if self.config.text_file_charset_detect.enable:
                charset = await detect_charset(fs_path, content_type)
                if charset is None:
                    charset = self.config.text_file_charset_detect.default
            else:
                charset = None

            basic_data = DAVPropertyBasicData(
                is_collection=is_collection,
                display_name=href_path.name,
                creation_date=DAVTime(stat_result.st_ctime),
                last_modified=DAVTime(stat_result.st_mtime),
                content_type="" if content_type is None else content_type,
                content_charset=charset,
                content_length=stat_result.st_size,
                content_encoding=content_encoding,
            )

        dav_property = DAVProperty(
            href_path=href_path, is_collection=is_collection, basic_data=basic_data
        )

        # extra
        if self.ignore_property_extra or request.propfind_only_fetch_basic:
            return dav_property

        # extra properties live in a sidecar file; a request for named
        # properties must report 404 for the missing ones even when no
        # sidecar exists yet
        properties_path = self._get_fs_properties_path(fs_path)
        extra_data: dict[DAVPropertyIdentity, str] = {}
        if await aiofiles.ospath.exists(properties_path):
            extra_data = await _load_extra_property(properties_path)
            dav_property.extra_data = extra_data

        s = set(request.propfind_extra_keys) - set(extra_data.keys())
        dav_property.extra_not_found = list(s)

        return dav_property

    async def _get_dav_property_d0(
        self, request: DAVRequest, href_path: DAVPath, fs_path: Path
    ) -> DAVProperty:
        stat_result = await aiofiles.os.stat(fs_path)

        return await self._create_dav_property_obj(
            request, href_path, fs_path, stat_result
        )

    async def _get_dav_property_d1_infinity(
        self,
        dav_properties: dict[DAVPath, DAVProperty],
        request: DAVRequest,
        href_path_base: DAVPath,
        fs_path_base: Path,
        infinity: bool,
        depth_limit: int = 99,  # TODO into config
    ) -> None:
        sub_dir_names: list[str] = list()
        dav_extension_info_file_extension = f".{DAV_EXTENSION_INFO_FILE_EXTENSION}"

        dir_entry_iter = await aiofiles.os.scandir(fs_path_base)
        for dir_entry in dir_entry_iter:
            if dir_entry.name.endswith(dav_extension_info_file_extension):
                # Found a WebDAV DAV info file
                continue

            href_path = href_path_base.add_child(dir_entry.name)
            fs_path = fs_path_base.joinpath(dir_entry.name)
            dav_properties[href_path] = await self._create_dav_property_obj(
                request, href_path, fs_path, dir_entry.stat()
            )

            if dir_entry.is_dir() and infinity:
                sub_dir_names.append(dir_entry.name)

        dir_entry_iter.close()

        if not infinity and depth_limit <= 0:
            return

        for sub_dir_name in sub_dir_names:
            await self._get_dav_property_d1_infinity(
                dav_properties=dav_properties,
                request=request,
                href_path_base=href_path_base.add_child(sub_dir_name),
                fs_path_base=fs_path_base.joinpath(sub_dir_name),
                infinity=infinity,
                depth_limit=depth_limit - 1,
            )

        return

    async def _do_propfind(self, request: DAVRequest) -> dict[DAVPath, DAVProperty]:
        dav_properties: dict[DAVPath, DAVProperty] = dict()

        base_fs_path = self._get_fs_path(request.dist_src_path, request.user.username)
        if not await aiofiles.ospath.exists(base_fs_path):
            return dav_properties

        dav_properties[request.src_path] = await self._get_dav_property_d0(
            request, request.src_path, base_fs_path
        )

        if request.depth != DAVDepth.ZERO and await aiofiles.ospath.isdir(base_fs_path):
            # is not d0 and is dir
            await self._get_dav_property_d1_infinity(
                dav_properties=dav_properties,
                request=request,
                href_path_base=request.src_path,
                fs_path_base=base_fs_path,
                infinity=request.depth == DAVDepth.INFINITY,
            )
            pass

        return dav_properties

    async def _do_proppatch(self, request: DAVRequest) -> int:
        if self.ignore_property_extra:
            return 207

        fs_path = self._get_fs_path(request.dist_src_path, request.user.username)
        properties_path = self._get_fs_properties_path(fs_path)
        if not await aiofiles.ospath.exists(fs_path):
            return 404

        success = await _update_extra_property(
            properties_path, request.proppatch_entries
        )
        if success:
            return 207

        return 409

    async def _do_mkcol(self, request: DAVRequest) -> int:
        fs_path = self._get_fs_path(request.dist_src_path, request.user.username)

        try:
            await aiofiles.os.mkdir(fs_path)

        except FileExistsError:
            logger.debug(f"directory already exists: {fs_path}")
            return 405

        except FileNotFoundError:
            logger.debug(f"miss parent path: {fs_path.parent}")
            return 409

        return 201

    async def _do_get(self, request: DAVRequest) -> tuple[
        int,
        DAVPropertyBasicData | None,
        DAVResponseBodyGenerator | None,
        DAVResponseContentRange | None,
    ]:
        fs_path = self._get_fs_path(request.dist_src_path, request.user.username)
        if not await aiofiles.ospath.exists(fs_path):
            return 404, None, None, None

        dav_property = await self._get_dav_property_d0(
            request, request.src_path, fs_path
        )

        # target is dir ---
        if fs_path.is_dir():
            return 200, dav_property.basic_data, None, None

        # target is file ---
        if len(request.ranges) == 0:
            # --- without range,response the entire file
            return (
                200,
                dav_property.basic_data,
                _dav_response_body_generator(fs_path),
                None,
            )

        response_content_range = get_response_content_range(
            request_ranges=request.ranges,
            file_size=dav_property.basic_data.content_length,
        )
        if response_content_range is None:
            # Range is not satisfiable
            # https://datatracker.ietf.org/doc/html/rfc7233#section-4.4
            return (416, dav_property.basic_data, None, None)

        if request.if_range and not request.if_range.match(
            etag=dav_property.basic_data.etag,
            last_modified=dav_property.basic_data.last_modified.http_date,
        ):
            # If-Range validator does not match: ignore Range,
            # response the entire file
            # https://datatracker.ietf.org/doc/html/rfc7233#section-3.2
            return (
                200,
                dav_property.basic_data,
                _dav_response_body_generator(fs_path),
                None,
            )

        # --- response file in range
        return (
            206,
            dav_property.basic_data,
            _dav_response_body_generator(fs_path, content_range=response_content_range),
            response_content_range,
        )

    async def _do_head(
        self, request: DAVRequest
    ) -> tuple[int, DAVPropertyBasicData | None]:
        fs_path = self._get_fs_path(request.dist_src_path, request.user.username)
        if not await aiofiles.ospath.exists(fs_path):  # TODO macOS 不区分大小写
            return 404, None

        dav_property = await self._get_dav_property_d0(
            request, request.src_path, fs_path
        )
        return 200, dav_property.basic_data

    async def _fs_delete(self, path: DAVPath, username: str | None) -> int:
        fs_path = self._get_fs_path(path, username)
        properties_path = self._get_fs_properties_path(fs_path)
        if not await aiofiles.ospath.exists(fs_path):
            return 404

        if await aiofiles.ospath.isdir(fs_path):
            shutil.rmtree(fs_path)  # TODO aiofile
            try:
                await aiofiles.os.remove(properties_path)
            except FileNotFoundError:
                pass

        else:
            await aiofiles.os.remove(fs_path)
            try:
                await aiofiles.os.remove(properties_path)
            except FileNotFoundError:
                pass

        return 204

    async def _do_delete(self, request: DAVRequest) -> int:
        return await self._fs_delete(request.dist_src_path, request.user.username)

    @staticmethod
    async def _remove_quiet(path: Path) -> None:
        # best effort cleanup: the directory may be unwritable or the file
        # may already be gone
        with suppress(OSError):
            await aiofiles.os.remove(path)

    async def _do_put(self, request: DAVRequest) -> int:
        fs_path = self._get_fs_path(request.dist_src_path, request.user.username)
        if await aiofiles.ospath.exists(fs_path):
            if await aiofiles.ospath.isdir(fs_path):
                return 405
        if not await aiofiles.ospath.isdir(fs_path.parent):
            return 409

        # write to a sibling temp file and rename on completion: an aborted
        # upload must not destroy an existing file, and a partial upload must
        # not be visible to other requests
        tmp_path = fs_path.with_name(f"{fs_path.name}.{uuid4().hex}.tmp")
        client_disconnected = False
        try:
            async with aiofiles.open(tmp_path, "wb") as f:
                more_body = True
                while more_body:
                    # the http scope only ever yields these two event types
                    request_data = cast(
                        "HTTPRequestEvent | HTTPDisconnectEvent",
                        await request.receive(),
                    )
                    if request_data["type"] == "http.disconnect":
                        # client went away mid-upload — persist nothing
                        client_disconnected = True
                        break

                    more_body = request_data["more_body"]
                    await f.write(request_data["body"])

        except PermissionError:
            await self._remove_quiet(tmp_path)
            return 403

        if client_disconnected:
            await self._remove_quiet(tmp_path)
            return 400

        await aiofiles.os.replace(tmp_path, fs_path)
        return 201

    @staticmethod
    def _copy_dir_depth0(
        src_path: Path, dst_path: Path, overwrite: bool = False
    ) -> bool:
        try:
            dst_path.mkdir(exist_ok=overwrite)  # TODO aiofile
            shutil.copystat(src_path, dst_path)  # TODO aiofile
        except (FileExistsError, FileNotFoundError):
            return False

        return True

    async def _copy_property_file(self, src_path: Path, des_path: Path) -> None:
        property_src_path = self._get_fs_properties_path(src_path)
        if not await aiofiles.ospath.exists(property_src_path):
            return

        property_des_path = self._get_fs_properties_path(des_path)
        if await aiofiles.ospath.exists(property_des_path):
            await aiofiles.os.remove(property_des_path)

        shutil.copy2(property_src_path, property_des_path)  # TODO: aiofiles
        return

    async def _do_copy(self, request: DAVRequest) -> int:
        def success_return(dst_existed: bool) -> int:
            # RFC 4918 9.8.4: 201 for a new resource, 204 when an existing
            # one was overwritten
            if request.overwrite and dst_existed:
                return 204
            else:
                return 201

        # check src_path
        src_fs_path = self._get_fs_path(request.dist_src_path, request.user.username)
        if not await aiofiles.ospath.exists(src_fs_path):
            return 404

        # check dst_path
        dst_fs_path = self._get_fs_path(request.dist_dst_path, request.user.username)
        if not await aiofiles.ospath.exists(dst_fs_path.parent):
            return 409
        dst_existed = await aiofiles.ospath.exists(dst_fs_path)
        if not request.overwrite and dst_existed:
            return 412

        # below ---
        # overwrite or not dst_fs_path.exists()

        # copy file
        if not await aiofiles.ospath.isdir(src_fs_path):
            shutil.copy2(src_fs_path, dst_fs_path)  # TODO aiofile
            await self._copy_property_file(src_fs_path, dst_fs_path)
            return success_return(dst_existed)

        # copy dir
        if request.depth != DAVDepth.ZERO:  # TODO .d1 .infinity
            # TODO aiofile
            shutil.copytree(src_fs_path, dst_fs_path, dirs_exist_ok=request.overwrite)
            await self._copy_property_file(src_fs_path, dst_fs_path)
            return success_return(dst_existed)

        if self._copy_dir_depth0(src_fs_path, dst_fs_path, request.overwrite):
            await self._copy_property_file(src_fs_path, dst_fs_path)
            return success_return(dst_existed)

        return 412

    async def _move_property_file(self, src_path: Path, des_path: Path) -> None:
        property_src_path = self._get_fs_properties_path(src_path)
        if not await aiofiles.ospath.exists(property_src_path):
            return

        property_des_path = self._get_fs_properties_path(des_path)
        if await aiofiles.ospath.exists(property_des_path):
            await aiofiles.os.remove(property_des_path)

        await aiofiles.os.rename(property_src_path, property_des_path)
        return

    async def _do_move(self, request: DAVRequest) -> int:
        def success_return(dst_existed: bool) -> int:
            # RFC 4918 9.9.4: 201 for a new resource, 204 when an existing
            # one was overwritten
            if request.overwrite and dst_existed:
                return 204
            else:
                return 201

        # https://tools.ietf.org/html/rfc4918#page-58
        # If a resource exists at the destination and the Overwrite header is
        #    "T", then prior to performing the move, the server MUST perform a
        #    DELETE with "Depth: infinity" on the destination resource
        # if overwrite:
        #     self._fs_delete(dst_path)

        src_fs_path = self._get_fs_path(request.dist_src_path, request.user.username)
        dst_fs_path = self._get_fs_path(request.dist_dst_path, request.user.username)
        src_exists = await aiofiles.ospath.exists(src_fs_path)
        # src_is_dir = await aiofiles.ospath.isdir(src_fs_path)
        dst_exists = await aiofiles.ospath.exists(dst_fs_path)
        dst_is_dir = await aiofiles.ospath.isdir(dst_fs_path)

        # check src_path
        if not src_exists:
            return 404

        # check dst_path
        if not await aiofiles.ospath.exists(dst_fs_path.parent):
            return 409
        if not request.overwrite and dst_exists:
            return 412

        # below ---
        # overwrite is True or dst_absolute_path.exists() is False

        # move it
        # if not overwrite and dst_exists and (src_is_dir != dst_is_dir):
        #     return 999

        if dst_exists:
            if dst_is_dir:
                # It's not a MERGE
                shutil.rmtree(dst_fs_path)  # TODO aiofile
            else:
                await aiofiles.os.remove(dst_fs_path)

        await aiofiles.os.rename(src_fs_path, dst_fs_path)
        await self._move_property_file(src_fs_path, dst_fs_path)
        return success_return(dst_exists)
