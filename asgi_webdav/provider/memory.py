from asyncio import Lock
from collections.abc import AsyncGenerator
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Optional

from asgi_webdav.constants import DAVDepth, DAVPath, DAVPropertyIdentity, DAVTime
from asgi_webdav.helpers import get_data_generator_from_content
from asgi_webdav.property import DAVProperty, DAVPropertyBasicData
from asgi_webdav.provider.dev_provider import DAVProvider
from asgi_webdav.request import DAVRequest


@dataclass
class FileSystemMember:
    name: str
    is_file: bool  # True => file, False => dir

    property_basic_data: DAVPropertyBasicData
    property_extra_data: dict[DAVPropertyIdentity, str]

    content: bytes | None = None
    children: dict[str, "FileSystemMember"] = field(default_factory=dict)

    @property
    def is_path(self):
        return not self.is_file

    def _new_child(
        self, name: str, content: bytes | None = None
    ) -> Optional["FileSystemMember"]:
        if name in self.children:
            return None

        if content is None:
            # is_path
            is_file = False
            content_length = 0
        else:
            is_file = True
            content_length = len(content)

        dav_time = DAVTime()
        if is_file:
            property_basic_data = DAVPropertyBasicData(
                is_collection=False,
                display_name=name,  # TODO check
                creation_date=dav_time,
                last_modified=dav_time,
                content_type="application/octet-stream",
                content_length=content_length,
            )
        else:
            property_basic_data = DAVPropertyBasicData(
                is_collection=True,
                display_name=name,
                creation_date=dav_time,
                last_modified=dav_time,
            )

        child_member = FileSystemMember(
            name=name,
            is_file=is_file,
            property_basic_data=property_basic_data,
            property_extra_data=dict(),
            content=content,
        )
        self.children.update(
            {
                name: child_member,
            }
        )
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

    def get_child(self, name: str) -> Optional["FileSystemMember"]:
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

    def get_member(self, path: DAVPath) -> Optional["FileSystemMember"]:
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
            paths.append(DAVPath(f"/{fs_member.name}"))

        return paths

    def member_exists(self, path: DAVPath) -> bool:
        point = self.get_member(path)
        if point is None:
            return False

        return True

    def _add_member_d0_deep_copy(
        self, src_member: "FileSystemMember", dst_member_name: str
    ):
        if src_member.is_file:
            self.children[dst_member_name] = deepcopy(src_member)
            self.children[dst_member_name].name = dst_member_name
            return

        # is_path
        if dst_member_name not in self.children:
            self.children[dst_member_name] = FileSystemMember(
                name=dst_member_name,
                property_basic_data=deepcopy(src_member.property_basic_data),
                property_extra_data=deepcopy(src_member.property_extra_data),
                is_file=False,
            )
            return

        self.children[dst_member_name].property_basic_data = deepcopy(
            src_member.property_basic_data
        )
        self.children[dst_member_name].property_extra_data = deepcopy(
            src_member.property_extra_data
        )

    def copy_member(
        self,
        src_path: DAVPath,
        dst_path: DAVPath,
        depth: DAVDepth = DAVDepth.infinity,
        overwrite: bool = False,  # TODO
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
            dst_member_parent._add_member_d0_deep_copy(src_member, dst_member_name)
            return True

        elif depth == DAVDepth.d1:
            dst_member_parent._add_member_d0_deep_copy(src_member, dst_member_name)
            if src_member.is_file:
                return True

            # is_path
            dst_member = dst_member_parent.get_child(dst_member_name)
            for src_member_child in src_member.children.values():
                if dst_member.child_exists(src_member_child.name) and not overwrite:
                    return False

                dst_member._add_member_d0_deep_copy(
                    src_member_child, src_member_child.name
                )

            return True

        # never here
        return False


class MemoryProvider(DAVProvider):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.support_content_range = True
        if self.home_dir:
            raise Exception("MemoryProvider does not currently support home_dir")

        dav_time = DAVTime()
        self.fs_root = FileSystemMember(
            name="root",
            property_basic_data=DAVPropertyBasicData(
                is_collection=True,
                display_name=self.prefix.name,  # TODO check
                creation_date=dav_time,
                last_modified=dav_time,
            ),
            property_extra_data=dict(),
            is_file=False,
        )
        self.fs_lock = Lock()

    def __repr__(self):
        return "memory:///"

    def _get_dav_property(
        self, request: DAVRequest, href_path: DAVPath, member_path: DAVPath
    ) -> DAVProperty:
        fs_member = self.fs_root.get_member(member_path)

        # basic
        dav_property = DAVProperty(
            href_path=href_path,
            is_collection=fs_member.is_path,
            basic_data=fs_member.property_basic_data,
        )

        # extra
        if request.propfind_only_fetch_basic:
            return dav_property

        for key in request.propfind_extra_keys:
            value = fs_member.property_extra_data.get(key)
            if value is None:
                dav_property.extra_not_found.append(key)
            else:
                dav_property.extra_data.update(
                    {
                        key: value,
                    }
                )

        return dav_property

    async def _do_propfind(self, request: DAVRequest) -> dict[DAVPath, DAVProperty]:
        dav_properties = dict()

        async with self.fs_lock:
            fs_member = self.fs_root.get_member(request.dist_src_path)
            if fs_member is None:
                return dav_properties

            member_paths = [request.dist_src_path]
            if fs_member.is_path and request.depth != DAVDepth.d0:
                member_paths += fs_member.get_all_child_member_path(request.depth)

            for member_path in member_paths:
                href_path = self.prefix.add_child(member_path)
                dav_properties[href_path] = self._get_dav_property(
                    request, href_path, member_path
                )

            return dav_properties

    async def _do_proppatch(self, request: DAVRequest) -> int:
        async with self.fs_lock:
            fs_member = self.fs_root.get_member(request.dist_src_path)
            if fs_member is None:
                return 404

            for sn_key, value, is_set_method in request.proppatch_entries:
                if is_set_method:
                    # set/update
                    fs_member.property_extra_data[sn_key] = value

                else:
                    # remove
                    if sn_key in fs_member.property_extra_data:
                        fs_member.property_extra_data.pop(sn_key)

            return 207  # TODO 409 ??

    async def _do_get(
        self, request: DAVRequest
    ) -> tuple[int, DAVPropertyBasicData | None, AsyncGenerator | None]:
        async with self.fs_lock:
            member = self.fs_root.get_member(request.dist_src_path)
            if member is None:
                return 404, None, None

            if member.is_path:
                return 200, member.property_basic_data, None

            # return 200, member.property_basic_data, member.get_content()
            if request.content_range:
                return (
                    200,
                    member.property_basic_data,
                    get_data_generator_from_content(
                        member.content,
                        content_range_start=request.content_range_start,
                        content_range_end=request.content_range_end,
                    ),
                )
            else:
                return (
                    200,
                    member.property_basic_data,
                    get_data_generator_from_content(member.content),
                )

    async def _do_head(
        self, request: DAVRequest
    ) -> tuple[int, DAVPropertyBasicData | None]:
        async with self.fs_lock:
            member = self.fs_root.get_member(request.dist_src_path)
            if member is None:
                return 404, None

            return 200, member.property_basic_data

    async def _do_mkcol(self, request: DAVRequest) -> int:
        if request.dist_src_path.raw == "/":
            return 201

        async with self.fs_lock:
            parent_member = self.fs_root.get_member(request.dist_src_path.parent)
            if parent_member is None:
                return 409

            if self.fs_root.member_exists(request.dist_src_path):
                return 405

            parent_member.add_path_child(request.dist_src_path.name)
            return 201

    async def _do_delete(self, request: DAVRequest) -> int:
        if request.dist_src_path.raw == "/":
            return 201

        async with self.fs_lock:
            member = self.fs_root.get_member(request.dist_src_path)
            if member is None:
                return 404

            parent_member = self.fs_root.get_member(request.dist_src_path.parent)
            parent_member.remove_child(request.dist_src_path.name)
            return 204

    async def _do_put(self, request: DAVRequest) -> int:
        async with self.fs_lock:
            member = self.fs_root.get_member(request.dist_src_path)
            if member and member.is_path:
                return 405

            content = b""
            more_body = True
            while more_body:
                request_data = await request.receive()
                more_body = request_data.get("more_body")

                content += request_data.get("body", b"")

            parent_member = self.fs_root.get_member(request.dist_src_path.parent)
            parent_member.add_file_child(request.dist_src_path.name, content)
            return 201

    async def _do_get_etag(self, request: DAVRequest) -> str:
        member = self.fs_root.get_member(request.dist_src_path)
        return member.property_basic_data.etag

    async def _do_copy(self, request: DAVRequest) -> int:
        def success_return() -> int:
            if request.overwrite:
                return 204
            else:
                return 201

        async with self.fs_lock:
            src_member = self.fs_root.get_member(request.dist_src_path)
            dst_member = self.fs_root.get_member(request.dist_dst_path)
            dst_member_parent = self.fs_root.get_member(request.dist_dst_path.parent)

            if dst_member_parent is None:
                return 409
            if src_member is None:
                return 403
            if dst_member and not request.overwrite:
                return 412

            # below ---
            # overwrite or dst_member is None
            if self.fs_root.copy_member(
                request.dist_src_path,
                request.dist_dst_path,
                request.depth,
                request.overwrite,
            ):
                return success_return()

            return 412

    async def _do_move(self, request: DAVRequest) -> int:
        def success_return() -> int:
            if request.overwrite:
                return 204
            else:
                return 201

        async with self.fs_lock:
            src_member_name = request.dist_src_path.name
            dst_member_name = request.dist_dst_path.name
            src_member_parent = self.fs_root.get_member(request.dist_src_path.parent)
            dst_member_parent = self.fs_root.get_member(request.dist_dst_path.parent)
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
                request.dist_src_path, request.dist_dst_path, DAVDepth.infinity, True
            )

            src_member_parent.remove_child(src_member_name)
            return success_return()
