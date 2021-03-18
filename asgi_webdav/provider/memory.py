from typing import Optional, AsyncGenerator
from asyncio import Lock
from dataclasses import dataclass, field
from copy import deepcopy

from asgi_webdav.constants import (
    DAVPath,
    DAVDepth,
    DAVPassport,
    DAVPropertyIdentity,
    # DAVPropertyPatches,
    DAVProperty,
)
from asgi_webdav.helpers import (
    DateTime,
    receive_all_data_in_one_call,
    generate_etag,
)
from asgi_webdav.request import DAVRequest
from asgi_webdav.provider.dev_provider import DAVProvider


@dataclass
class FileSystemMember:
    name: str
    is_file: bool  # True => file, False => path

    basic_property: dict[str, str]
    extra_property: dict[DAVPropertyIdentity, str]

    content: Optional[bytes] = None
    children: dict[str, 'FileSystemMember'] = field(default_factory=dict)

    @property
    def is_path(self):
        return not self.is_file

    async def get_content(self) -> AsyncGenerator:
        file_block_size = 64 * 1024
        data = self.content
        more_body = True
        while more_body:
            send_data = data[:file_block_size]
            data = data[file_block_size:]
            more_body = len(data) == file_block_size

            yield send_data, more_body

    def _new_child(
        self, name: str, content: Optional[bytes] = None
    ) -> Optional['FileSystemMember']:
        if name in self.children:
            return None

        if content is None:
            # is_path
            is_file = False
            content_length = 0
        else:
            is_file = True
            content_length = len(content)

        dav_time = DateTime()
        basic_property = {
            'displayname': '',

            'creationdate': dav_time.iso_8601(),
            'getlastmodified': dav_time.iso_850(),

        }
        if is_file:
            basic_property.update({
                'getetag': generate_etag(content_length, dav_time.timestamp),

                'getcontenttype': 'application/octet-stream',
                'getcontentlength': str(content_length),
                'encoding': 'utf-8',
            })
        else:
            basic_property.update({
                'getetag': generate_etag(0.0, dav_time.timestamp),

                'getcontenttype': 'httpd/unix-directory',
            })

        child_member = FileSystemMember(
            name=name,
            is_file=is_file,

            basic_property=basic_property,
            extra_property=dict(),

            content=content,
        )
        self.children.update({
            name: child_member,
        })
        return child_member

    def add_path_child(self, name: str) -> bool:
        child_member = self._new_child(name, None)
        if child_member is None:
            return False

        return True

    def add_file_child(self, name: str, content: bytes) -> bool:
        child_member = self._new_child(name, content)
        if child_member is None:
            return False

        return True

    def get_child(self, name: str) -> Optional['FileSystemMember']:
        member = self.children.get(name)
        return member

    def child_exists(self, name: str) -> bool:
        return name in self.children

    def remove_child(self, name) -> bool:
        member = self.children.get(name)
        if member is None:
            return False

        if member.is_path:
            member.remove_all_child()

        self.children.pop(name)
        return True

    def remove_all_child(self):
        for child_name in list(self.children):
            self.remove_child(child_name)

    def get_member(self, path: DAVPath) -> Optional['FileSystemMember']:
        fs_member = self
        for name in path.parts:
            fs_member = fs_member.get_child(name)
            if fs_member is None:
                return None

        return fs_member

    def get_all_child_member_path(self, depth: DAVDepth) -> list[DAVPath]:
        """depth == DAVDepth.d1 or DAVDepth.infinity"""
        # TODO DAVDepth.infinity
        paths = list()
        for fs_member in self.children.values():
            paths.append(DAVPath('/{}'.format(fs_member.name)))

        return paths

    def member_exists(self, path: DAVPath) -> bool:
        point = self.get_member(path)
        if point is None:
            return False

        return True

    def _add_member_d0_deep_copy(
        self, src_member: 'FileSystemMember', dst_member_name: str
    ):
        if src_member.is_file:
            self.children[dst_member_name] = deepcopy(src_member)
            self.children[dst_member_name].name = dst_member_name
            return

        # is_path
        if dst_member_name not in self.children:
            self.children[dst_member_name] = FileSystemMember(
                name=dst_member_name,
                basic_property=deepcopy(src_member.basic_property),
                extra_property=deepcopy(src_member.extra_property),
                is_file=False
            )
            return

        self.children[dst_member_name].basic_property = deepcopy(
            src_member.basic_property
        )
        self.children[dst_member_name].extra_property = deepcopy(
            src_member.extra_property
        )

    def copy_member(
        self, src_path: DAVPath, dst_path: DAVPath,
        depth: DAVDepth = DAVDepth.infinity, overwrite: bool = False  # TODO
    ) -> bool:
        src_member_name = src_path.name
        dst_member_name = dst_path.name
        src_member_parent = self.get_member(src_path.parent)
        dst_member_parent = self.get_member(dst_path.parent)
        if dst_member_parent.child_exists(dst_member_name) and not overwrite:
            return False

        src_member = src_member_parent.get_child(src_member_name)

        if depth == DAVDepth.infinity:
            # TODO ???
            dst_member_parent.children[dst_member_name] = deepcopy(src_member)
            return True

        elif depth == DAVDepth.d0:
            dst_member_parent._add_member_d0_deep_copy(
                src_member, dst_member_name
            )
            return True

        elif depth == DAVDepth.d1:
            dst_member_parent._add_member_d0_deep_copy(
                src_member, dst_member_name
            )
            if src_member.is_file:
                return True

            # is_path
            dst_member = dst_member_parent.get_child(dst_member_name)
            for src_member_child in src_member.children.values():
                if dst_member.child_exists(
                    src_member_child.name
                ) and not overwrite:
                    return False

                dst_member._add_member_d0_deep_copy(
                    src_member_child, src_member_child.name
                )

            return True

        # never here
        return False


class MemoryProvider(DAVProvider):
    def __init__(self, read_only=False):
        super().__init__()
        self.read_only = read_only  # TODO

        self.fs_root = FileSystemMember(
            name='root',
            basic_property=dict(),
            extra_property=dict(),
            is_file=False
        )
        self.fs_lock = Lock()

    def __repr__(self):
        return 'memory:///'

    def _get_dav_property(
        self, request: DAVRequest, passport: DAVPassport, path: DAVPath
    ) -> DAVProperty:
        prop = DAVProperty()
        prop.href_path = passport.src_prefix.add_child(path)

        fs_member = self.fs_root.get_member(path)
        prop.is_collection = fs_member.is_path
        prop.basic_data = fs_member.basic_property

        # extra
        prop.extra_data = dict()
        prop.extra_not_found = list()

        if request.propfind_only_fetch_basic:
            return prop

        for key in request.propfind_extra_keys:
            value = fs_member.extra_property.get(key)
            if value is None:
                prop.extra_not_found.append(key)
            else:
                prop.extra_data.update({
                    key: value,
                })

        return prop

    async def _do_propfind(
        self, request: DAVRequest, passport: DAVPassport
    ) -> Optional[list[DAVProperty]]:
        async with self.fs_lock:
            fs_member = self.fs_root.get_member(passport.src_path)
            if fs_member is None:
                return None

            properties = list()
            paths = [passport.src_path]
            if fs_member.is_path and request.depth != DAVDepth.d0:
                paths += fs_member.get_all_child_member_path(request.depth)

            for path in paths:
                properties.append(
                    self._get_dav_property(request, passport, path)
                )

            return properties

    async def _do_proppatch(
        self, request: DAVRequest, passport: DAVPassport
    ) -> int:
        async with self.fs_lock:
            fs_member = self.fs_root.get_member(passport.src_path)
            if fs_member is None:
                return 404

            for sn_key, value, is_set_method in request.proppatch_entries:
                if is_set_method:
                    # set/update
                    fs_member.extra_property[sn_key] = value

                else:
                    # remove
                    if sn_key in fs_member.extra_property:
                        fs_member.extra_property.pop(sn_key)

            return 207  # TODO 409 ??

    async def _do_get(
        self, request: DAVRequest, passport: DAVPassport
    ) -> tuple[int, dict[str, str], Optional[AsyncGenerator]]:
        async with self.fs_lock:
            member = self.fs_root.get_member(passport.src_path)
            if member is None:
                return 404, dict(), None

            return 200, member.basic_property, member.get_content()

    async def _do_head(
        self, request: DAVRequest, passport: DAVPassport
    ) -> tuple[int, dict[str, str]]:
        async with self.fs_lock:
            member = self.fs_root.get_member(passport.src_path)
            if member is None:
                return 404, dict()

            return 200, member.basic_property

    async def _do_mkcol(
        self, request: DAVRequest, passport: DAVPassport
    ) -> int:
        if passport.src_path.raw == '/':
            return 201

        async with self.fs_lock:
            parent_member = self.fs_root.get_member(passport.src_path.parent)
            if parent_member is None:
                return 409

            if self.fs_root.member_exists(passport.src_path):
                return 405

            parent_member.add_path_child(passport.src_path.name)
            return 201

    async def _do_delete(
        self, request: DAVRequest, passport: DAVPassport
    ) -> int:
        if passport.src_path.raw == '/':
            return 201

        async with self.fs_lock:
            member = self.fs_root.get_member(passport.src_path)
            if member is None:
                return 404

            parent_member = self.fs_root.get_member(passport.src_path.parent)
            parent_member.remove_child(passport.src_path.name)
            return 204

    async def _do_put(
        self, request: DAVRequest, passport: DAVPassport
    ) -> int:
        async with self.fs_lock:
            member = self.fs_root.get_member(passport.src_path)
            if member and member.is_path:
                return 405

            content = await receive_all_data_in_one_call(request.receive)

            parent_member = self.fs_root.get_member(passport.src_path.parent)
            parent_member.add_file_child(passport.src_path.name, content)
            return 201

    async def _do_get_etag(
        self, request: DAVRequest, passport: DAVPassport
    ) -> str:
        member = self.fs_root.get_member(passport.src_path)
        return member.basic_property.get('getetag')

    async def _do_copy(
        self, request: DAVRequest, passport: DAVPassport
    ) -> int:
        def sucess_return() -> int:
            if request.overwrite:
                return 204
            else:
                return 201

        async with self.fs_lock:
            src_member = self.fs_root.get_member(passport.src_path)
            dst_member = self.fs_root.get_member(passport.dst_path)
            # src_member_parent = self.fs_root.get_member(
            #     passport.src_path.parent
            # )
            dst_member_parent = self.fs_root.get_member(
                passport.dst_path.parent
            )

            if dst_member_parent is None:
                return 409
            if src_member is None:
                return 403
            if dst_member and not request.overwrite:
                return 412

            # below ---
            # overwrite or dst_member is None
            if self.fs_root.copy_member(
                passport.src_path, passport.dst_path,
                request.depth, request.overwrite
            ):
                return sucess_return()

            return 412

    async def _do_move(
        self, request: DAVRequest, passport: DAVPassport
    ) -> int:
        def sucess_return() -> int:
            if request.overwrite:
                return 204
            else:
                return 201

        async with self.fs_lock:
            src_member_name = passport.src_path.name
            dst_member_name = passport.dst_path.name
            src_member_parent = self.fs_root.get_member(
                passport.src_path.parent
            )
            dst_member_parent = self.fs_root.get_member(
                passport.dst_path.parent
            )
            src_member = src_member_parent.get_child(src_member_name)
            dst_exists = dst_member_parent.child_exists(dst_member_name)

            if src_member_parent is None:
                return 409
            if dst_member_parent is None:
                return 400  # TODO
            if src_member is None:
                return 403
            if dst_exists and not request.overwrite:
                return 412

            # below ---
            # overwrite or dst_member is None
            if dst_exists:
                dst_member_parent.remove_child(dst_member_name)

            self.fs_root.copy_member(
                passport.src_path, passport.dst_path,
                DAVDepth.infinity, True
            )

            src_member_parent.remove_child(src_member_name)
            return sucess_return()
