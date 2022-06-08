import json
import shutil
from collections.abc import AsyncGenerator
from logging import getLogger
from pathlib import Path
from stat import S_ISDIR

import aiofiles
from aiofiles.os import stat as aio_stat

from asgi_webdav.constants import (
    RESPONSE_DATA_BLOCK_SIZE,
    DAVDepth,
    DAVPath,
    DAVPropertyIdentity,
    DAVPropertyPatches,
    DAVTime,
)
from asgi_webdav.exception import ProviderInitException
from asgi_webdav.helpers import detect_charset, generate_etag, guess_type
from asgi_webdav.property import DAVProperty, DAVPropertyBasicData
from asgi_webdav.provider.dev_provider import DAVProvider
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


def _parser_property_from_json(data) -> dict[DAVPropertyIdentity, str]:
    try:
        if not isinstance(data, dict):
            raise ValueError

        props = data.get("property")
        if not isinstance(props, list):
            raise ValueError

    except ValueError:
        return dict()

    data = [DAVPropertyIdentity((tuple(k), v)) for k, v in props]
    return dict(data)


async def _load_extra_property(file: Path) -> dict[DAVPropertyIdentity, str]:
    async with aiofiles.open(file, "r") as fp:
        tmp = await fp.read()
        try:
            data = json.loads(tmp)

        except json.JSONDecodeError as e:
            print(e)
            return dict()

    return _parser_property_from_json(data)


async def _update_extra_property(
    file: Path, property_patches: list[DAVPropertyPatches]
) -> bool:
    if not file.exists():
        file.touch()

    async with aiofiles.open(file, "r+") as fp:
        tmp = await fp.read()
        if len(tmp) == 0:
            data = dict()

        else:
            try:
                data = json.loads(tmp)

            except json.JSONDecodeError as e:
                print(e)
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


async def _dav_response_data_generator(
    resource_abs_path: Path,
    content_range_start: int | None = None,
    content_range_end: int | None = None,
    block_size: int = RESPONSE_DATA_BLOCK_SIZE,
) -> AsyncGenerator[bytes, bool]:
    async with aiofiles.open(resource_abs_path, mode="rb") as f:
        if content_range_start is None:
            more_body = True
            while more_body:
                data = await f.read(block_size)
                more_body = len(data) == block_size

                yield data, more_body

        else:
            # support HTTP Header: Range
            await f.seek(content_range_start)

            more_body = True
            while more_body:
                if (
                    content_range_end is not None
                    and content_range_start + block_size > content_range_end
                ):
                    read_data_block_size = content_range_end - content_range_start
                else:
                    read_data_block_size = block_size

                data = await f.read(read_data_block_size)
                data_length = len(data)
                content_range_start += data_length
                more_body = data_length == read_data_block_size

                yield data, more_body


class FileSystemProvider(DAVProvider):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.support_content_range = True

        self.root_path = Path(self.uri[7:])

        if not self.root_path.exists():
            raise ProviderInitException(
                'Init FileSystemProvider failed, "{}" is not exists.'.format(
                    self.root_path
                )
            )

    def __repr__(self):
        if self.home_dir:
            return "file://{}/{{user name}}".format(self.root_path)
        else:
            return "file://{}".format(self.root_path)

    def _get_fs_path(self, path: DAVPath, username: str | None) -> Path:
        if self.home_dir and username:
            return self.root_path.joinpath(username, *path.parts)

        return self.root_path.joinpath(*path.parts)

    @staticmethod
    def _get_fs_properties_path(path: Path) -> Path:
        return path.parent.joinpath(
            "{}.{}".format(path.name, DAV_EXTENSION_INFO_FILE_EXTENSION)
        )

    async def _get_dav_property(
        self, request: DAVRequest, href_path: DAVPath, fs_path: Path
    ) -> DAVProperty:
        stat_result = await aio_stat(fs_path)
        is_collection = S_ISDIR(stat_result.st_mode)

        # basic
        if is_collection:
            basic_data = DAVPropertyBasicData(
                is_collection=S_ISDIR(stat_result.st_mode),
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
                is_collection=S_ISDIR(stat_result.st_mode),
                display_name=href_path.name,
                creation_date=DAVTime(stat_result.st_ctime),
                last_modified=DAVTime(stat_result.st_mtime),
                content_type=content_type,
                content_charset=charset,
                content_length=stat_result.st_size,
                content_encoding=content_encoding,
            )

        dav_property = DAVProperty(
            href_path=href_path, is_collection=is_collection, basic_data=basic_data
        )

        # extra
        if request.propfind_only_fetch_basic:
            return dav_property

        properties_path = self._get_fs_properties_path(fs_path)
        if properties_path.exists():
            extra_data = await _load_extra_property(properties_path)
            dav_property.extra_data = extra_data

            s = set(request.propfind_extra_keys) - set(extra_data.keys())
            dav_property.extra_not_found = list(s)

        return dav_property

    async def _do_propfind(self, request: DAVRequest) -> dict[DAVPath, DAVProperty]:
        dav_properties = dict()

        base_fs_path = self._get_fs_path(request.dist_src_path, request.user.username)
        if not base_fs_path.exists():
            return dav_properties

        child_fs_paths = list()
        if request.depth != DAVDepth.d0 and base_fs_path.is_dir():
            if request.depth == DAVDepth.d1:
                glob_param = "*"
            elif request.depth == DAVDepth.infinity:
                # raise TODO !!!
                glob_param = "**"
            else:
                raise

            child_fs_paths = base_fs_path.glob(glob_param)

        dav_property = await self._get_dav_property(
            request, request.src_path, base_fs_path
        )
        dav_properties[request.src_path] = dav_property

        for item in child_fs_paths:
            new_href_path = request.src_path.add_child(item.name)
            dav_property = await self._get_dav_property(request, new_href_path, item)
            dav_properties[new_href_path] = dav_property

        return dav_properties

    async def _do_proppatch(self, request: DAVRequest) -> int:
        fs_path = self._get_fs_path(request.dist_src_path, request.user.username)
        properties_path = self._get_fs_properties_path(fs_path)
        if not fs_path.exists():
            return 404

        sucess = await _update_extra_property(
            properties_path, request.proppatch_entries
        )
        if sucess:
            return 207

        return 409

    async def _do_mkcol(self, request: DAVRequest) -> int:
        fs_path = self._get_fs_path(request.dist_src_path, request.user.username)
        if fs_path.exists():
            return 405

        if not fs_path.parent.exists():
            logger.debug("miss parent path: {}".format(fs_path.parent))
            return 409

        try:
            fs_path.mkdir(exist_ok=True)  # TODO exist_ok ??

        except (FileNotFoundError, FileExistsError):
            return 409  # TODO ??

        return 201

    async def _do_get(
        self, request: DAVRequest
    ) -> tuple[int, DAVPropertyBasicData | None, AsyncGenerator | None]:
        fs_path = self._get_fs_path(request.dist_src_path, request.user.username)
        if not fs_path.exists():
            return 404, None, None

        dav_property = await self._get_dav_property(request, request.src_path, fs_path)

        if fs_path.is_dir():
            return 200, dav_property.basic_data, None

        # is file
        if request.content_range:
            data = _dav_response_data_generator(
                fs_path,
                content_range_start=request.content_range_start,
                content_range_end=request.content_range_end,
            )
            http_status = 206
        else:
            data = _dav_response_data_generator(fs_path)
            http_status = 200

        return http_status, dav_property.basic_data, data

    async def _do_head(
        self, request: DAVRequest
    ) -> tuple[int, DAVPropertyBasicData | None]:
        fs_path = self._get_fs_path(request.dist_src_path, request.user.username)
        if not fs_path.exists():  # TODO macOS 不区分大小写
            return 404, None

        dav_property = await self._get_dav_property(request, request.src_path, fs_path)
        return 200, dav_property.basic_data

    def _fs_delete(self, path: DAVPath, username: str | None) -> int:
        fs_path = self._get_fs_path(path, username)
        properties_path = self._get_fs_properties_path(fs_path)
        if not fs_path.exists():
            return 404

        if fs_path.is_dir():
            shutil.rmtree(fs_path)
            properties_path.unlink(missing_ok=True)
        else:
            fs_path.unlink(missing_ok=True)
            properties_path.unlink(missing_ok=True)

        return 204

    async def _do_delete(self, request: DAVRequest) -> int:
        return self._fs_delete(request.dist_src_path, request.user.username)

    async def _do_put(self, request: DAVRequest) -> int:
        fs_path = self._get_fs_path(request.dist_src_path, request.user.username)
        if fs_path.exists():
            if fs_path.is_dir():
                return 405

            # return 409 # TODO overwrite???? 11. owner_modify..........

        async with aiofiles.open(fs_path, "wb") as f:
            more_body = True
            while more_body:
                request_data = await request.receive()
                more_body = request_data.get("more_body")

                data = request_data.get("body", b"")
                await f.write(data)

        return 201

    async def _do_get_etag(self, request: DAVRequest) -> str:
        fs_path = self._get_fs_path(request.dist_src_path, request.user.username)
        stat_result = await aio_stat(fs_path)
        return generate_etag(stat_result.st_size, stat_result.st_mtime)

    @staticmethod
    def _copy_dir_depth0(
        src_path: Path, dst_path: Path, overwrite: bool = False
    ) -> bool:
        try:
            dst_path.mkdir(exist_ok=overwrite)
            shutil.copystat(src_path, dst_path)
        except (FileExistsError, FileNotFoundError):
            return False

        return True

    @staticmethod
    def _copy_property_file(src_path: Path, des_path: Path):
        property_src_path = src_path.parent.joinpath(
            "{}.{}".format(src_path.name, DAV_EXTENSION_INFO_FILE_EXTENSION)
        )
        if not property_src_path.exists():
            return
        property_des_path = des_path.parent.joinpath(
            "{}.{}".format(des_path.name, DAV_EXTENSION_INFO_FILE_EXTENSION)
        )
        if property_des_path.exists():
            property_des_path.unlink()

        shutil.copy2(property_src_path, property_des_path)
        return

    async def _do_copy(self, request: DAVRequest) -> int:
        def sucess_return() -> int:
            if request.overwrite:
                return 204
            else:
                return 201

        # check src_path
        src_fs_path = self._get_fs_path(request.dist_src_path, request.user.username)
        if not src_fs_path.exists():
            return 403

        # check dst_path
        dst_fs_path = self._get_fs_path(request.dist_dst_path, request.user.username)
        if not dst_fs_path.parent.exists():
            return 409
        if not request.overwrite and dst_fs_path.exists():
            return 412

        # below ---
        # overwrite or not dst_fs_path.exists()

        # copy file
        if not src_fs_path.is_dir():
            shutil.copy2(src_fs_path, dst_fs_path)
            self._copy_property_file(src_fs_path, dst_fs_path)
            return sucess_return()

        # copy dir
        if request.depth != DAVDepth.d0:
            shutil.copytree(src_fs_path, dst_fs_path, dirs_exist_ok=request.overwrite)
            self._copy_property_file(src_fs_path, dst_fs_path)
            return sucess_return()

        if self._copy_dir_depth0(src_fs_path, dst_fs_path, request.overwrite):
            self._copy_property_file(src_fs_path, dst_fs_path)
            return sucess_return()

        return 412

    @staticmethod
    def _move_with_overwrite(src_absolute_path: Path, dst_absolute_path: Path):
        shutil.copytree(src_absolute_path, dst_absolute_path, dirs_exist_ok=True)
        shutil.rmtree(src_absolute_path)
        return

    @staticmethod
    def _move_property_file(src_path: Path, des_path: Path):
        # if src_path.is_dir():
        #     # TODO ???
        #     return

        property_src_path = src_path.parent.joinpath(
            "{}.{}".format(src_path.name, DAV_EXTENSION_INFO_FILE_EXTENSION)
        )
        if not property_src_path.exists():
            return
        property_des_path = des_path.parent.joinpath(
            "{}.{}".format(des_path.name, DAV_EXTENSION_INFO_FILE_EXTENSION)
        )
        if property_des_path.exists():
            property_des_path.unlink()

        shutil.move(property_src_path, property_des_path)
        return

    async def _do_move(self, request: DAVRequest) -> int:
        def sucess_return() -> int:
            if request.overwrite:
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
        src_exists = src_fs_path.exists()
        src_is_dir = src_fs_path.is_dir()
        dst_exists = dst_fs_path.exists()
        dst_is_dir = dst_fs_path.is_dir()

        # check src_path
        if not src_exists:
            return 403

        # check dst_path
        if not dst_fs_path.parent.exists():
            return 409
        if not request.overwrite and dst_exists:
            return 412

        # below ---
        # overwrite or not dst_absolute_path.exists()

        # move it
        # if not overwrite and dst_exists and (src_is_dir != dst_is_dir):
        #     return 999

        if not dst_exists or not src_is_dir:
            shutil.move(src_fs_path, dst_fs_path)
            self._move_property_file(src_fs_path, dst_fs_path)
            return sucess_return()

        if request.overwrite and dst_exists and (src_is_dir != dst_is_dir):
            if dst_is_dir:
                shutil.rmtree(dst_fs_path)
            else:
                dst_fs_path.unlink()

            shutil.move(src_fs_path, dst_fs_path)
            self._move_property_file(src_fs_path, dst_fs_path)
            return sucess_return()

        self._move_with_overwrite(src_fs_path, dst_fs_path)
        self._move_property_file(src_fs_path, dst_fs_path)
        return sucess_return()
