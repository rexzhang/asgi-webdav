import os
import mimetypes
import shutil
import json
from stat import S_ISDIR
from pathlib import Path
# from http import HTTPStatus
from typing import Optional, Callable, NewType

import msgpack
import aiofiles
from aiofiles.os import stat as aio_stat
from prettyprinter import pprint

from asgi_webdav.constants import (
    DAVProperty,
    DAVPropertyIdentity,
    DAVPropertyExtra,
    DAVPropertyPatches,
    DAVPath,
    DAVPassport,
)
from asgi_webdav.helpers import DateTime
from asgi_webdav.request import DAVRequest
from asgi_webdav.provider.dev_provider import DAVProvider

DAV_PROPERTIES_EXTENSION_NAME = 'dav_properties'

DAVPropertyFileContentType = NewType(
    'DAVPropertyFileContentType',
    tuple[DAVPropertyIdentity, str]
)


async def _load_extend_property(file: Path):
    async with aiofiles.open(file, 'r') as fp:
        tmp = await fp.read()
        try:
            data = json.loads(tmp)
            # if not isinstance(data, DAVPropertyFileContentType):
            #     return None

        # except msgpack.UnpackException as e:
        except json.JSONDecodeError as e:
            print(e)
            return None

    data = [tuple((tuple(k), v)) for k, v in data]
    data = dict(data)
    return data


async def _dump_extend_property(
    file: Path, property_patches: list[DAVPropertyPatches]
) -> bool:
    # async with aiofiles.open(file, 'bw+') as fp:
    async with aiofiles.open(file, 'w+') as fp:
        tmp = await fp.read()
        if len(tmp) == 0:
            data = dict()

        else:
            try:
                # data = msgpack.loads(tmp)
                # if not isinstance(data, DAVPropertyExtra):
                #     return False
                data = json.loads(tmp)
                if not isinstance(data, DAVPropertyFileContentType):
                    return False

            # except msgpack.UnpackException as e:
            except json.JSONDecodeError as e:
                print(e)
                return False

            data = dict(data)

        for sn_key, value, is_set_method in property_patches:
            if is_set_method:
                data[sn_key] = value
            else:
                data.pop(sn_key, None)

        # tmp = msgpack.dumps(data)
        # print('~~~~~~~')
        # pprint(data)
        data = [x for x in data.items()]
        # pprint(data)
        # print('~~~~~~~')
        tmp = json.dumps(data)
        await fp.seek(0)
        await fp.write(tmp)

    return True


class FileSystemProvider(DAVProvider):
    def __init__(self, root_path, read_only=False):
        super().__init__()
        self.root_path = Path(root_path)
        self.read_only = read_only  # TODO

    def _get_absolute_path(self, path: DAVPath) -> Path:
        return self.root_path.joinpath(*path.parts)

    def _get_properties_path(self, path: DAVPath) -> Path:
        return self.root_path.joinpath(
            '{}.{}'.format(*path.parts, DAV_PROPERTIES_EXTENSION_NAME)
        )

    @staticmethod
    async def _get_os_stat(path) -> Optional[os.stat_result]:
        try:
            stat_result = os.stat(path)
            return stat_result

        except FileNotFoundError:
            return None

    async def _get_dav_property(
        self, request: DAVRequest, path: DAVPath, absolute_path: Path
    ) -> DAVProperty:
        properties_path = self._get_properties_path(path)

        stat_result = await aio_stat(absolute_path)
        is_dir = S_ISDIR(stat_result.st_mode)
        if is_dir:
            prop = DAVProperty(
                path=path,
                display_name=absolute_path.name,

                creation_date=stat_result.st_ctime,
                last_modified=stat_result.st_mtime,

                resource_type_is_dir=True,
                content_type='httpd/unix-directory',

                content_length=None,
                encoding=None,
            )

        else:
            content_type, encoding = mimetypes.guess_type(absolute_path)
            if not content_type:
                content_type = 'application/octet-stream'
            if not encoding:
                encoding = 'utf-8'

            prop = DAVProperty(
                path=path,
                display_name=absolute_path.name,

                creation_date=stat_result.st_ctime,
                last_modified=stat_result.st_mtime,

                resource_type_is_dir=False,
                content_type=content_type,

                content_length=stat_result.st_size,
                encoding=encoding,
            )

            if properties_path.exists():
                extra_data = await _load_extend_property(properties_path)
                prop.extra = extra_data

                s = set(request.propfind_entries) - set(extra_data.keys())
                prop.extra_not_found = list(s)

        return prop

    async def _do_propfind(
        self, request: DAVRequest, passport: DAVPassport
    ) -> bytes:
        absolute_path = self._get_absolute_path(passport.src_path)

        child_paths = list()
        if request.depth != 0 and absolute_path.is_dir():
            if request.depth == 1:
                glob_param = '*'
            elif request.depth == -1:  # 'infinity
                # raise TODO !!!
                glob_param = '*'
            else:
                raise

            child_paths = absolute_path.glob(glob_param)

        properties = [
            await self._get_dav_property(
                request, passport.src_path, absolute_path
            ),
        ]
        for item in child_paths:
            new_path = passport.src_path.append_child(item.name)
            properties.append(
                await self._get_dav_property(request, new_path, item)
            )

        return await self._create_propfind_response(properties, passport)

    async def _do_proppatch(
        self, request: DAVRequest, passport: DAVPassport
    ) -> int:
        absolute_path = self._get_absolute_path(passport.src_path)
        properties_path = self._get_properties_path(passport.src_path)
        if not absolute_path.exists():
            return 404

        sucess = await _dump_extend_property(
            properties_path, request.proppatch_entries
        )
        if sucess:
            return 207

        return 409

    async def _do_mkcol(self, path: DAVPath) -> int:
        absolute_path = self._get_absolute_path(path)
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
        self, request: DAVRequest, path: DAVPath, send: Callable
    ) -> int:
        # TODO _get_dav_property()
        absolute_path = self._get_absolute_path(path)
        if not absolute_path.exists():
            return 404

        dav_property = await self._get_dav_property(
            request, path, absolute_path
        )
        headers = [
            (b'Content-Encodings', bytes(
                dav_property.encoding, encoding='utf-8'
            )),
            (b'Content-Type', bytes(
                dav_property.content_type, encoding='utf-8'
            )),
            (b'Content-Length', bytes(
                str(dav_property.content_length), encoding='utf-8'
            )),
            (b'Accept-Ranges', b'bytes'),
            (b'Last-Modified', bytes(
                DateTime(dav_property.last_modified).iso_8601(),
                encoding='utf-8'
            )),
            (b'ETag', bytes(dav_property.etag, encoding='utf-8')),
        ]

        # send headers
        await send({
            'type': 'http.response.start',
            'status': 200,
            'headers': headers,
        })
        # if is_head:
        #     await send({
        #         'type': 'http.response.body',
        #     })
        #
        #     return

        _FILE_BLOCK_SIZE = 64 * 1024
        # send file
        async with aiofiles.open(absolute_path, mode="rb") as f:
            more_body = True
            while more_body:
                data = await f.read(_FILE_BLOCK_SIZE)
                more_body = len(data) == _FILE_BLOCK_SIZE
                await send(
                    {
                        "type": "http.response.body",
                        "body": data,
                        "more_body": more_body,
                    }
                )

        return 200

    async def _do_head(self, path: DAVPath) -> bool:
        # TODO _get_dav_property()
        absolute_path = self._get_absolute_path(path)
        # print(absolute_path)
        if absolute_path.exists():  # macOS 不区分大小写
            return True

        return False

    async def _do_delete(self, path: DAVPath) -> int:
        absolute_path = self._get_absolute_path(path)
        properties_path = self._get_properties_path(path)
        if not absolute_path.exists():
            return 404

        if absolute_path.is_dir():
            shutil.rmtree(absolute_path)
        else:
            properties_path.unlink(missing_ok=True)
            absolute_path.unlink(missing_ok=True)

        return 204

    async def _do_put(self, path: DAVPath, receive: Callable) -> int:
        absolute_path = self._get_absolute_path(path)
        if absolute_path.exists():
            if absolute_path.is_dir():
                return 405

            # return 409 # TODO overwrite???? 11. owner_modify..........

        request_data = await receive()
        data = request_data.get('body')
        absolute_path.write_bytes(data)
        return 201

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

    async def _do_copy(
        self, src_path: DAVPath, dst_path: DAVPath, depth: int,
        overwrite: bool = False
    ) -> int:
        def sucess_return() -> int:
            if overwrite:
                return 204
            else:
                return 201

        # check src_path
        src_absolute_path = self._get_absolute_path(src_path)
        if not src_absolute_path.exists():
            return 403

        # check dst_path
        dst_absolute_path = self._get_absolute_path(dst_path)
        if not dst_absolute_path.parent.exists():
            return 409
        if not overwrite and dst_absolute_path.exists():
            return 412

        # below ---
        # overwrite or not dst_absolute_path.exists()

        # copy file
        if not src_absolute_path.is_dir():
            shutil.copy2(src_absolute_path, dst_absolute_path)
            return sucess_return()

        # copy dir
        if depth != 0:
            shutil.copytree(
                src_absolute_path, dst_absolute_path, dirs_exist_ok=overwrite
            )
            return sucess_return()

        if self._copy_dir_depth0(
            src_absolute_path, dst_absolute_path, overwrite
        ):
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
        if src_path.is_dir():
            # TODO ???
            return

        property_src_path = src_path.parent.joinpath(
            '{}.{}'.format(src_path.name, DAV_PROPERTIES_EXTENSION_NAME)
        )
        if not property_src_path.exists():
            return
        property_des_path = des_path.parent.joinpath(
            '{}.{}'.format(des_path.name, DAV_PROPERTIES_EXTENSION_NAME)
        )
        if property_des_path.exists():
            property_des_path.unlink()

        shutil.move(property_src_path, property_des_path)
        return

    async def _do_move(
        self, src_path: DAVPath, dst_path: DAVPath, overwrite: bool = False
    ) -> int:
        def sucess_return() -> int:
            if overwrite:
                return 204
            else:
                return 201

        src_absolute_path = self._get_absolute_path(src_path)
        dst_absolute_path = self._get_absolute_path(dst_path)
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
        if not overwrite and dst_exists:
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

        if overwrite and dst_exists and (src_is_dir != dst_is_dir):
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
