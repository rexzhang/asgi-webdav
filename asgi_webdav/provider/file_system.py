from typing import Optional, AsyncGenerator
import mimetypes
import shutil
import json

from stat import S_ISDIR
from pathlib import Path
# from http import HTTPStatus

import aiofiles
from aiofiles.os import stat as aio_stat

from asgi_webdav.constants import (
    DAVPath,
    DAVDepth,
    DAVPassport,
    DAVPropertyIdentity,
    DAVPropertyPatches,
    DAVProperty,
)
from asgi_webdav.exception import WebDAVException
from asgi_webdav.helpers import (
    DateTime,
    receive_all_data_in_one_call,
    generate_etag,
)
from asgi_webdav.request import DAVRequest
from asgi_webdav.provider.dev_provider import DAVProvider

DAV_EXTENSION_INFO_FILE_EXTENSION = 'DAV'
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

        props = data.get('property')
        if not isinstance(props, list):
            raise ValueError

    except ValueError:
        return dict()

    data = [tuple((tuple(k), v)) for k, v in props]
    data = dict(data)
    return data


async def _load_extra_property(file: Path) -> dict[DAVPropertyIdentity, str]:
    async with aiofiles.open(file, 'r') as fp:
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

    async with aiofiles.open(file, 'r+') as fp:
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

        data = {
            'property': [tuple((tuple(k), v)) for k, v in data.items()]
        }
        tmp = json.dumps(data)
        await fp.seek(0)
        await fp.write(tmp)
        await fp.truncate()

    return True


async def _dav_response_data_generator(
    resource_abs_path: Path  # TODO!!
) -> AsyncGenerator[bytes, bool]:
    file_block_size = 64 * 1024
    async with aiofiles.open(resource_abs_path, mode="rb") as f:
        more_body = True
        while more_body:
            data = await f.read(file_block_size)
            more_body = len(data) == file_block_size

            yield data, more_body
            # await asyncio.sleep(delay)


class FileSystemProvider(DAVProvider):
    def __init__(self, root_path, read_only=False):
        super().__init__()
        self.root_path = Path(root_path)
        self.read_only = read_only  # TODO

        if not self.root_path.exists():
            raise WebDAVException(
                'Init FileSystemProvider failed, {} is not exists.'.format(
                    self.root_path
                )
            )

    def __repr__(self):
        return 'file://{}'.format(self.root_path)

    def _get_absolute_path(self, path: DAVPath) -> Path:
        return self.root_path.joinpath(*path.parts)

    def _get_properties_path(self, path: DAVPath) -> Path:
        abs_path = self.root_path.joinpath(*path.parts)
        return abs_path.parent.joinpath(
            '{}.{}'.format(abs_path.name, DAV_EXTENSION_INFO_FILE_EXTENSION)
        )

    async def _get_dav_property(
        self, path: DAVPath, abs_path: Path,
        is_only_fetch_basic_property: bool,
        extra_keys: list[DAVPropertyIdentity]
    ) -> DAVProperty:
        stat_result = await aio_stat(abs_path)
        is_dir = S_ISDIR(stat_result.st_mode)

        p = DAVProperty()
        p.path = path
        p.is_collection = is_dir

        # basic
        p.basic_data = {
            'displayname': abs_path.name,
            'getetag': generate_etag(
                stat_result.st_size, stat_result.st_mtime
            ),
            'creationdate': DateTime(stat_result.st_ctime).iso_8601(),
            'getlastmodified': DateTime(stat_result.st_mtime).iso_850(),
        }
        if p.is_collection:
            p.basic_data.update({
                # 'resourcetype': 'collection',  # TODO

                'getcontenttype': 'httpd/unix-directory'
            })
        else:
            content_type, encoding = mimetypes.guess_type(abs_path)
            if not content_type:
                content_type = 'application/octet-stream'
            if not encoding:
                encoding = 'utf-8'

            p.basic_data.update({
                # 'resourcetype': None,  # TODO

                'getcontenttype': content_type,
                'getcontentlength': str(stat_result.st_size),
                'encoding': encoding

            })

        # extra
        if is_only_fetch_basic_property:
            p.extra_data = dict()
            p.extra_not_found = list()
            return p

        properties_path = self._get_properties_path(path)
        if properties_path.exists():
            extra_data = await _load_extra_property(properties_path)
            p.extra_data = extra_data

            s = set(extra_keys) - set(extra_data.keys())
            p.extra_not_found = list(s)

        else:
            p.extra_data = dict()
            p.extra_not_found = list()

        return p

    async def _do_propfind(
        self, request: DAVRequest, passport: DAVPassport
    ) -> Optional[list[DAVProperty]]:
        base_abs_path = self._get_absolute_path(passport.src_path)
        if not base_abs_path.exists():
            return None

        child_abs_paths = list()
        if request.depth != DAVDepth.d0 and base_abs_path.is_dir():
            if request.depth == DAVDepth.d1:
                glob_param = '*'
            elif request.depth == DAVDepth.infinity:
                # raise TODO !!!
                glob_param = '*'
            else:
                raise

            child_abs_paths = base_abs_path.glob(glob_param)

        properties = [
            await self._get_dav_property(
                passport.src_path, base_abs_path,
                request.propfind_only_fetch_basic,
                request.propfind_extra_keys,
            ),
        ]
        for item in child_abs_paths:
            new_path = passport.src_path.add_child(item.name)
            properties.append(
                await self._get_dav_property(
                    new_path, item,
                    request.propfind_only_fetch_basic,
                    request.propfind_extra_keys,
                )
            )

        return properties

    async def _do_proppatch(
        self, request: DAVRequest, passport: DAVPassport
    ) -> int:
        absolute_path = self._get_absolute_path(passport.src_path)
        properties_path = self._get_properties_path(passport.src_path)
        if not absolute_path.exists():
            return 404

        sucess = await _update_extra_property(
            properties_path, request.proppatch_entries
        )
        if sucess:
            return 207

        return 409

    async def _do_mkcol(
        self, request: DAVRequest, passport: DAVPassport
    ) -> int:
        absolute_path = self._get_absolute_path(passport.src_path)
        if absolute_path.exists():
            return 405

        if not absolute_path.parent.exists():
            return 409

        try:
            absolute_path.mkdir(exist_ok=True)  # TODO exist_ok ??

        except (FileNotFoundError, FileExistsError):
            return 409  # TODO ??

        return 201

    async def _do_get(
        self, request: DAVRequest, passport: DAVPassport
    ) -> tuple[int, dict[str, str], Optional[AsyncGenerator]]:
        absolute_path = self._get_absolute_path(passport.src_path)
        if not absolute_path.exists():
            return 404, dict(), None

        dav_property = await self._get_dav_property(
            passport.src_path, absolute_path,
            request.propfind_only_fetch_basic,
            request.propfind_extra_keys
        )
        data = _dav_response_data_generator(absolute_path)
        return 200, dav_property.basic_data, data

    async def _do_head(
        self, request: DAVRequest, passport: DAVPassport
    ) -> tuple[int, dict[str, str]]:
        absolute_path = self._get_absolute_path(passport.src_path)
        if not absolute_path.exists():  # TODO macOS 不区分大小写
            return 404, dict()

        dav_property = await self._get_dav_property(
            passport.src_path, absolute_path,
            request.propfind_only_fetch_basic,
            request.propfind_extra_keys
        )
        return 200, dav_property.basic_data

    def _fs_delete(self, path: DAVPath) -> int:
        absolute_path = self._get_absolute_path(path)
        properties_path = self._get_properties_path(path)
        if not absolute_path.exists():
            return 404

        if absolute_path.is_dir():
            shutil.rmtree(absolute_path)
            properties_path.unlink(missing_ok=True)
        else:
            absolute_path.unlink(missing_ok=True)
            properties_path.unlink(missing_ok=True)

        return 204

    async def _do_delete(
        self, request: DAVRequest, passport: DAVPassport
    ) -> int:
        return self._fs_delete(passport.src_path)

    async def _do_put(
        self, request: DAVRequest, passport: DAVPassport
    ) -> int:
        absolute_path = self._get_absolute_path(passport.src_path)
        if absolute_path.exists():
            if absolute_path.is_dir():
                return 405

            # return 409 # TODO overwrite???? 11. owner_modify..........

        data = await receive_all_data_in_one_call(request.receive)
        absolute_path.write_bytes(data)
        return 201

    async def _do_get_etag(
        self, request: DAVRequest, passport: DAVPassport
    ) -> str:
        abs_path = self._get_absolute_path(passport.src_path)
        stat_result = await aio_stat(abs_path)
        return generate_etag(
            stat_result.st_size, stat_result.st_mtime
        )

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
            '{}.{}'.format(src_path.name, DAV_EXTENSION_INFO_FILE_EXTENSION)
        )
        if not property_src_path.exists():
            return
        property_des_path = des_path.parent.joinpath(
            '{}.{}'.format(des_path.name, DAV_EXTENSION_INFO_FILE_EXTENSION)
        )
        if property_des_path.exists():
            property_des_path.unlink()

        shutil.copy2(property_src_path, property_des_path)
        return

    async def _do_copy(
        self, request: DAVRequest, passport: DAVPassport
    ) -> int:
        def sucess_return() -> int:
            if request.overwrite:
                return 204
            else:
                return 201

        # check src_path
        src_absolute_path = self._get_absolute_path(passport.src_path)
        if not src_absolute_path.exists():
            return 403

        # check dst_path
        dst_absolute_path = self._get_absolute_path(passport.dst_path)
        if not dst_absolute_path.parent.exists():
            return 409
        if not request.overwrite and dst_absolute_path.exists():
            return 412

        # below ---
        # overwrite or not dst_absolute_path.exists()

        # copy file
        if not src_absolute_path.is_dir():
            shutil.copy2(src_absolute_path, dst_absolute_path)
            self._copy_property_file(src_absolute_path, dst_absolute_path)
            return sucess_return()

        # copy dir
        if request.depth != DAVDepth.d0:
            shutil.copytree(
                src_absolute_path, dst_absolute_path,
                dirs_exist_ok=request.overwrite
            )
            self._copy_property_file(src_absolute_path, dst_absolute_path)
            return sucess_return()

        if self._copy_dir_depth0(
            src_absolute_path, dst_absolute_path, request.overwrite
        ):
            self._copy_property_file(src_absolute_path, dst_absolute_path)
            return sucess_return()

        return 412

    @staticmethod
    def _move_with_overwrite(src_absolute_path: Path, dst_absolute_path: Path):
        shutil.copytree(
            src_absolute_path, dst_absolute_path, dirs_exist_ok=True
        )
        shutil.rmtree(src_absolute_path)
        return

    @staticmethod
    def _move_property_file(src_path: Path, des_path: Path):
        # if src_path.is_dir():
        #     # TODO ???
        #     return

        property_src_path = src_path.parent.joinpath(
            '{}.{}'.format(src_path.name, DAV_EXTENSION_INFO_FILE_EXTENSION)
        )
        if not property_src_path.exists():
            return
        property_des_path = des_path.parent.joinpath(
            '{}.{}'.format(des_path.name, DAV_EXTENSION_INFO_FILE_EXTENSION)
        )
        if property_des_path.exists():
            property_des_path.unlink()

        shutil.move(property_src_path, property_des_path)
        return

    async def _do_move(
        self, request: DAVRequest, passport: DAVPassport
    ) -> int:
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

        src_absolute_path = self._get_absolute_path(passport.src_path)
        dst_absolute_path = self._get_absolute_path(passport.dst_path)
        src_exists = src_absolute_path.exists()
        src_is_dir = src_absolute_path.is_dir()
        dst_exists = dst_absolute_path.exists()
        dst_is_dir = dst_absolute_path.is_dir()

        # check src_path
        if not src_exists:
            return 403

        # check dst_path
        if not dst_absolute_path.parent.exists():
            return 409
        if not request.overwrite and dst_exists:
            return 412

        # below ---
        # overwrite or not dst_absolute_path.exists()

        # move it
        # if not overwrite and dst_exists and (src_is_dir != dst_is_dir):
        #     return 999

        if not dst_exists or not src_is_dir:
            shutil.move(src_absolute_path, dst_absolute_path)
            self._move_property_file(src_absolute_path, dst_absolute_path)
            return sucess_return()

        if request.overwrite and dst_exists and (src_is_dir != dst_is_dir):
            if dst_is_dir:
                shutil.rmtree(dst_absolute_path)
            else:
                dst_absolute_path.unlink()

            shutil.move(src_absolute_path, dst_absolute_path)
            self._move_property_file(src_absolute_path, dst_absolute_path)
            return sucess_return()

        self._move_with_overwrite(src_absolute_path, dst_absolute_path)
        self._move_property_file(src_absolute_path, dst_absolute_path)
        return sucess_return()
