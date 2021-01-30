import os
import mimetypes
import shutil
from pathlib import Path
from hashlib import md5
from datetime import datetime
# from http import HTTPStatus
from typing import Optional

import aiofiles
from aiofiles.os import stat as aio_stat


class DAVProvider:
    async def do_head(self, path) -> bool:
        raise NotImplementedError

    async def do_propfind(self, path):
        raise NotImplementedError

    async def do_delete(self, path) -> int:
        raise NotImplementedError

    async def do_mkcol(self, path) -> int:
        raise NotImplementedError

    async def do_put(self, path, receive) -> int:
        raise NotImplementedError

    async def do_get(self, path, send) -> int:
        raise NotImplementedError

    async def do_copy(
        self, src_path: str, dst_path: str, depth: int, overwrite: bool = False
    ) -> int:
        raise NotImplementedError

    async def do_move(
        self, src_path: str, dst_path: str, overwrite: bool = False
    ) -> int:
        raise NotImplementedError


class FileSystemProvider(DAVProvider):
    def __init__(self, root_path, read_only=False):
        self.root_path = Path(root_path)
        self.read_only = read_only

    def _get_absolute_path(self, path) -> Path:
        return self.root_path.joinpath(path)

    async def do_head(self, path) -> bool:
        absolute_path = self._get_absolute_path(path)
        print(absolute_path)
        if absolute_path.exists():  # macOS 不区分大小写
            return True

        return False

    async def do_propfind(self, path):
        absolute_path = self._get_absolute_path(path)
        sr = await self._get_os_stat(absolute_path)
        if sr is None:
            return None

        filename = absolute_path.name
        print(type(path), path, type(str(sr.st_mtime)), str(sr.st_mtime))
        data = {
            'creationdate': datetime.fromtimestamp(sr.st_ctime).isoformat(),
            'getlastmodified': datetime.fromtimestamp(sr.st_mtime).isoformat(),
            'displayname': filename,
            'getetag': md5(
                '{}{}'.format(path, str(sr.st_mtime)).encode('utf8')
            ),
        }
        if absolute_path.is_dir():
            data.update({
                'resourcetype': '<D:collection/>',
            })
        else:
            data.update({
                'getcontentlength': sr.st_size,
                'getcontenttype': mimetypes.guess_type(filename),
                'getcontentlanguage': None,
            })

        return data

    def get_properties(self):
        pass

    @staticmethod
    async def _get_os_stat(path) -> Optional[os.stat_result]:
        try:
            stat_result = os.stat(path)
            return stat_result

        except FileNotFoundError:
            return None

    def _rmdir(self, absolute_path: Path):
        for item in absolute_path.glob('*'):
            if item.is_dir():
                self._rmdir(item)
                continue

            item.unlink()

        absolute_path.rmdir()
        return

    async def do_delete(self, path) -> int:
        absolute_path = self._get_absolute_path(path)
        # print(absolute_path)
        if not absolute_path.exists():
            return 404

        if absolute_path.is_dir():
            # self._rmdir(absolute_path)
            shutil.rmtree(absolute_path)
        else:
            absolute_path.unlink(missing_ok=True)

        return 204

    async def do_mkcol(self, path) -> int:
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

    async def do_put(self, path, receive) -> int:
        absolute_path = self._get_absolute_path(path)
        if absolute_path.exists():
            if absolute_path.is_dir():
                return 405

            return 409

        r = await receive()
        data = r.get('body')
        absolute_path.write_bytes(data)
        return 201

    async def do_get(self, path, send) -> int:
        absolute_path = self._get_absolute_path(path)
        if not absolute_path.exists():
            return 404

        data = absolute_path.read_bytes()

        # create headers
        content_type, encoding = mimetypes.guess_type(absolute_path)
        if content_type:
            content_type = bytes(content_type, encoding='utf-8')
        else:
            content_type = b''
        if encoding:
            encoding = bytes(encoding, encoding='utf-8')
        else:
            encoding = b''
        stat_result = await aio_stat(absolute_path)
        file_size = bytes(str(stat_result.st_size), encoding='utf-8')
        last_modified = bytes(
            datetime.fromtimestamp(stat_result.st_mtime).isoformat(),
            encoding='utf-8'
        )
        headers = [
            (b'Content-Encodings', encoding),
            (b'Content-Type', content_type),
            (b'Content-Length', file_size),
            (b'Accept-Ranges', b'bytes'),
            (b'Last-Modified', last_modified),
            (b'ETag',
             md5(file_size + last_modified).hexdigest().encode('utf-8')),
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

    async def do_copy(
        self, src_path: str, dst_path: str, depth: int, overwrite: bool = False
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

    async def do_move(
        self, src_path: str, dst_path: str, overwrite: bool = False
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
            return sucess_return()

        if overwrite and dst_exists and (src_is_dir != dst_is_dir):
            if dst_is_dir:
                shutil.rmtree(dst_absolute_path)
            else:
                dst_absolute_path.unlink()

            shutil.move(src_absolute_path, dst_absolute_path)
            return sucess_return()

        self._move_with_overwrite(src_absolute_path, dst_absolute_path)
        return sucess_return()
