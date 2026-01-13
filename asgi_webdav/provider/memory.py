from __future__ import annotations

from asyncio import Lock
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from asgiref.typing import HTTPRequestEvent

from asgi_webdav.constants import (
    DAVDepth,
    DAVPath,
    DAVPropertyIdentity,
    DAVResponseBodyGenerator,
    DAVResponseContentRange,
    DAVTime,
)
from asgi_webdav.property import DAVProperty, DAVPropertyBasicData
from asgi_webdav.provider.common import (
    DAVProvider,
    DAVProviderFeature,
    get_response_content_range,
)
from asgi_webdav.request import DAVRequest
from asgi_webdav.response import get_response_body_generator


@dataclass(slots=True)
class MemoryFSNode:
    node_path: DAVPath

    is_file: bool
    is_folder: bool = field(init=False)
    content: bytes

    property_basic_data: DAVPropertyBasicData
    property_extra_data: dict[DAVPropertyIdentity, str]

    children: dict[str, MemoryFSNode] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.is_folder = not self.is_file

    def update_content(self, content: bytes) -> None:
        self.content = content
        self.property_basic_data.last_modified = DAVTime()


class MemoryFS:
    data: dict[DAVPath, MemoryFSNode]  # dict[ProviderRelativePath, NodeObject]
    prefix_path: DAVPath

    def __init__(self, prefix_path: DAVPath = DAVPath("/")) -> None:
        self.data = dict()
        self.prefix_path = prefix_path
        self._init_root_node()

    def _init_root_node(self) -> None:
        dav_time = DAVTime()
        root_node = MemoryFSNode(
            node_path=self.prefix_path,
            is_file=False,
            property_basic_data=DAVPropertyBasicData(
                is_collection=True,
                display_name=self.prefix_path.name,
                creation_date=dav_time,
                last_modified=dav_time,
            ),
            property_extra_data=dict(),
            content=b"",
        )

        self.data[DAVPath("/")] = root_node

    def add_node(
        self,
        dst_node_path: DAVPath,
        dst_node_parent: MemoryFSNode | None = None,
        content: bytes | None = None,
        property_basic_data: DAVPropertyBasicData | None = None,
        property_extra_data: dict[DAVPropertyIdentity, str] | None = None,
    ) -> MemoryFSNode:
        """node must not exist"""
        if dst_node_parent is None:
            dst_node_parent = self.data.get(dst_node_path.parent)
            if dst_node_parent is None:
                raise ValueError("parent node not exist")

        name = dst_node_path.name
        dav_time = DAVTime()
        if content is None:
            # is folder
            if property_basic_data is None:
                property_basic_data = DAVPropertyBasicData(
                    is_collection=True,
                    display_name=name,
                    creation_date=dav_time,
                    last_modified=dav_time,
                )
            if property_extra_data is None:
                property_extra_data = dict()

            node = MemoryFSNode(
                node_path=dst_node_path,
                is_file=False,
                property_basic_data=property_basic_data,
                property_extra_data=property_extra_data,
                content=b"",
            )

        else:
            # is file
            if property_basic_data is None:
                property_basic_data = DAVPropertyBasicData(
                    is_collection=False,
                    display_name=name,
                    creation_date=dav_time,
                    last_modified=dav_time,
                    content_type="application/octet-stream",
                    content_length=len(content),
                )
            if property_extra_data is None:
                property_extra_data = dict()

            node = MemoryFSNode(
                node_path=dst_node_path,
                is_file=True,
                property_basic_data=property_basic_data,
                property_extra_data=property_extra_data,
                content=content,
            )

        self.data[dst_node_path] = node
        dst_node_parent.children[name] = node
        return node

    def has_node(self, node_path: DAVPath) -> bool:
        return node_path in self.data

    def get_node(self, node_path: DAVPath) -> MemoryFSNode | None:
        return self.data.get(node_path)

    def has_child(self, node_path: DAVPath, name: str) -> bool:
        node = self.data.get(node_path)
        if node is None:
            return False

        return name in node.children

    def get_node_children(
        self, node: MemoryFSNode, recursive: bool = False
    ) -> list[MemoryFSNode]:
        result = list()
        for child in node.children.values():
            if recursive:
                result.extend(self.get_node_children(node=child, recursive=True))

            result.append(child)

        return result

    def del_tree(self, node: MemoryFSNode, parent_node: MemoryFSNode) -> None:
        if node.is_folder:
            for child in list(node.children.values()):
                self.del_tree(node=child, parent_node=node)

        self.data.pop(node.node_path)
        parent_node.children.pop(node.node_path.name)

    def del_node(self, node: MemoryFSNode) -> bool:
        parent_node = self.get_node(node.node_path.parent)
        if parent_node is None:
            return False

        self.del_tree(node=node, parent_node=parent_node)
        return True

    def copy_node(
        self,
        src_node: MemoryFSNode,
        dst_path: DAVPath,
        dst_node_parent: MemoryFSNode,
        depth: DAVDepth = DAVDepth.INFINITY,
        overwrite: bool = False,
    ) -> bool:
        # cleanup dst
        dst_node = self.get_node(dst_path)
        if dst_node is not None:
            if overwrite:
                self.del_tree(dst_node, dst_node_parent)
            else:
                return False

        # copy
        match depth:
            case DAVDepth.ZERO:
                self.add_node(
                    dst_node_path=dst_path,
                    dst_node_parent=dst_node_parent,
                    content=src_node.content,
                    property_basic_data=deepcopy(src_node.property_basic_data),
                    property_extra_data=deepcopy(src_node.property_extra_data),
                )

            case DAVDepth.ONE:
                self.copy_tree(
                    src_node=src_node,
                    dst_path=dst_path,
                    dst_node_parent=dst_node_parent,
                    recursive=False,
                )

            case DAVDepth.INFINITY:
                self.copy_tree(
                    src_node=src_node,
                    dst_path=dst_path,
                    dst_node_parent=dst_node_parent,
                    recursive=True,
                )

        return True

    def copy_tree(
        self,
        src_node: MemoryFSNode,
        dst_path: DAVPath,
        dst_node_parent: MemoryFSNode,
        recursive: bool,
    ) -> None:
        """dst_path must not exist"""
        if src_node.is_file:
            self.add_node(
                dst_node_path=dst_path,
                dst_node_parent=dst_node_parent,
                content=src_node.content,
                property_basic_data=deepcopy(src_node.property_basic_data),
                property_extra_data=deepcopy(src_node.property_extra_data),
            )
            return

        # src_node is folder ---
        # deepcopy to dsc
        dst_node = self.add_node(
            dst_node_path=dst_path,
            dst_node_parent=dst_node_parent,
            property_basic_data=deepcopy(src_node.property_basic_data),
            property_extra_data=deepcopy(src_node.property_extra_data),
        )

        for child_name, child_node in src_node.children.items():
            # deepcopy child to dst
            if child_node.is_folder:
                if recursive:
                    self.copy_tree(
                        src_node=child_node,
                        dst_path=dst_path.add_child(child_name),
                        dst_node_parent=dst_node,
                        recursive=True,
                    )
                else:
                    self.add_node(
                        dst_node_path=dst_path.add_child(child_name),
                        dst_node_parent=dst_node,
                        property_basic_data=child_node.property_basic_data,
                        property_extra_data=child_node.property_extra_data,
                    )

            else:
                # is file
                self.add_node(
                    dst_node_path=dst_path.add_child(child_name),
                    dst_node_parent=dst_node,
                    content=child_node.content,
                    property_basic_data=deepcopy(src_node.property_basic_data),
                    property_extra_data=deepcopy(src_node.property_extra_data),
                )

        return

    def move_node(
        self,
        src_node: MemoryFSNode,
        src_node_parent: MemoryFSNode,
        dst_path: DAVPath,
        dst_node_parent: MemoryFSNode,
        overwrite: bool = False,
    ) -> bool:
        # cleanup dst
        dst_node = self.get_node(dst_path)
        if dst_node is not None:
            if overwrite:
                self.del_node(dst_node)
            else:
                return False

        self.move_tree(
            src_node=src_node,
            src_node_parent=src_node_parent,
            dst_node_path=dst_path,
            dst_node_parent=dst_node_parent,
            recursive=False,
        )
        return True

    def move_tree(
        self,
        src_node: MemoryFSNode,
        src_node_parent: MemoryFSNode,
        dst_node_path: DAVPath,
        dst_node_parent: MemoryFSNode,
        recursive: bool,
    ) -> None:
        """src_path must be a folder, dst_path must not exist"""
        if src_node.is_file:
            # move to dst
            self.add_node(
                dst_node_path=dst_node_path,
                dst_node_parent=dst_node_parent,
                content=src_node.content,
                property_basic_data=src_node.property_basic_data,
                property_extra_data=src_node.property_extra_data,
            )
            # delete src
            self.del_tree(src_node, src_node_parent)
            return

        # src_node is folder ---
        # move to dst
        dst_node = self.add_node(
            dst_node_path=dst_node_path,
            dst_node_parent=dst_node_parent,
            property_basic_data=src_node.property_basic_data,
            property_extra_data=src_node.property_extra_data,
        )

        for child_name, child_node in list(src_node.children.items()):
            # move child to dst
            if child_node.is_folder:
                if recursive:
                    self.move_tree(
                        src_node=child_node,
                        src_node_parent=src_node,
                        dst_node_path=dst_node_path.add_child(child_name),
                        dst_node_parent=dst_node,
                        recursive=True,
                    )
                else:
                    self.add_node(
                        dst_node_path=dst_node_path.add_child(child_name),
                        dst_node_parent=dst_node,
                        property_basic_data=child_node.property_basic_data,
                        property_extra_data=child_node.property_extra_data,
                    )

            else:
                # is file
                self.add_node(
                    dst_node_path=dst_node_path.add_child(child_name),
                    dst_node_parent=dst_node,
                    content=child_node.content,
                    property_basic_data=child_node.property_basic_data,
                    property_extra_data=child_node.property_extra_data,
                )

        # delete src node tree
        self.del_tree(src_node, src_node_parent)
        return


class MemoryProvider(DAVProvider):
    type = "memory"
    feature = DAVProviderFeature(
        content_range=True,
        home_dir=False,
    )

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)

        self.fs = MemoryFS(self.prefix)
        self.fs_lock = Lock()

    def __repr__(self) -> str:
        return "memory:///"

    async def _get_res_etag(self, request: DAVRequest) -> str:
        node = self.fs.get_node(request.dist_src_path)
        if node is None:
            raise  # TODO

        return node.property_basic_data.etag

    async def _get_res_etag_from_res_dist_path(
        self, res_dist_path: DAVPath, username: str | None = None
    ) -> str:
        node = self.fs.get_node(res_dist_path)
        if node is None:
            raise  # TODO

        return node.property_basic_data.etag

    def _get_dav_property(
        self, request: DAVRequest, node: MemoryFSNode, node_path: DAVPath
    ) -> tuple[DAVPath, DAVProperty]:
        """-> href_path, dav_property"""
        href_path = self.prefix.add_child(node_path)
        # basic
        dav_property = DAVProperty(
            href_path=href_path,
            is_collection=node.is_folder,
            basic_data=node.property_basic_data,
        )

        # extra
        if request.propfind_only_fetch_basic:
            return href_path, dav_property

        for key in request.propfind_extra_keys:
            value = node.property_extra_data.get(key)
            if value is None:
                dav_property.extra_not_found.append(key)
            else:
                dav_property.extra_data.update(
                    {
                        key: value,
                    }
                )

        return href_path, dav_property

    async def _do_propfind(self, request: DAVRequest) -> dict[DAVPath, DAVProperty]:
        dav_properties: dict[DAVPath, DAVProperty] = dict()
        async with self.fs_lock:
            node = self.fs.get_node(request.dist_src_path)
            if node is None:
                return dav_properties

            match request.depth:
                case DAVDepth.ZERO:
                    href_path, dav_property = self._get_dav_property(
                        request=request,
                        node=node,
                        node_path=request.dist_src_path,
                    )
                    dav_properties[href_path] = dav_property
                    return dav_properties

                case DAVDepth.ONE:
                    recursive = False
                case DAVDepth.INFINITY:
                    recursive = True

            for child_node in self.fs.get_node_children(node, recursive):
                href_path, dav_property = self._get_dav_property(
                    request=request, node=child_node, node_path=child_node.node_path
                )
                dav_properties[href_path] = dav_property

            return dav_properties

    async def _do_proppatch(self, request: DAVRequest) -> int:
        if self.ignore_property_extra:
            return 207

        async with self.fs_lock:
            node = self.fs.get_node(request.dist_src_path)
            if node is None:
                return 404

            for sn_key, value, is_set_method in request.proppatch_entries:
                if is_set_method:
                    # set/update
                    node.property_extra_data[sn_key] = value

                else:
                    # remove
                    if sn_key in node.property_extra_data:
                        node.property_extra_data.pop(sn_key)

            return 207  # TODO 409 ??

    async def _do_get(self, request: DAVRequest) -> tuple[
        int,
        DAVPropertyBasicData | None,
        DAVResponseBodyGenerator | None,
        DAVResponseContentRange | None,
    ]:
        async with self.fs_lock:
            node = self.fs.get_node(request.dist_src_path)
            if node is None:
                return 404, None, None, None

            # target is dir ---
            if node.is_folder:
                return 200, node.property_basic_data, None, None

            # target is file ---
            if len(request.ranges) == 0:
                # --- response the entire file
                return (
                    200,
                    node.property_basic_data,
                    get_response_body_generator(node.content),
                    None,
                )

            response_content_range = get_response_content_range(
                request_ranges=request.ranges,
                file_size=node.property_basic_data.content_length,
            )
            if response_content_range is None:
                # can't get correct content range
                # TODO: logging
                return (
                    200,
                    node.property_basic_data,
                    get_response_body_generator(node.content),
                    None,
                )

            if request.if_range and not request.if_range.match(
                etag=node.property_basic_data.etag,
                last_modified=node.property_basic_data.last_modified.http_date,
            ):
                # IfRange is not match
                # TODO: other soultion: return 200 with full file, control by config
                return (416, node.property_basic_data, None, response_content_range)

            # --- response file in range
            return (
                206,
                node.property_basic_data,
                get_response_body_generator(
                    node.content,
                    response_content_range.content_start,
                    response_content_range.content_end,
                ),
                response_content_range,
            )

    async def _do_head(
        self, request: DAVRequest
    ) -> tuple[int, DAVPropertyBasicData | None]:
        async with self.fs_lock:
            node = self.fs.get_node(request.dist_src_path)
            if node is None:
                return 404, None

            return 200, node.property_basic_data

    async def _do_mkcol(self, request: DAVRequest) -> int:
        if request.dist_src_path.raw == "/":
            return 201

        async with self.fs_lock:
            parent_node = self.fs.get_node(request.dist_src_path.parent)
            if parent_node is None:
                return 409
            if self.fs.has_node(request.dist_src_path):
                return 405

            self.fs.add_node(request.dist_src_path, dst_node_parent=parent_node)
            return 201

    async def _do_delete(self, request: DAVRequest) -> int:
        if request.dist_src_path.raw == "/":
            return 201

        async with self.fs_lock:
            node = self.fs.get_node(request.dist_src_path)
            if node is None:
                return 404

            self.fs.del_node(node)  # TOOD: failed
            return 204

    async def _do_put(self, request: DAVRequest) -> int:
        async with self.fs_lock:
            node = self.fs.get_node(request.dist_src_path)
            if node and node.is_folder:
                return 405

            parent_node = self.fs.get_node(request.dist_src_path.parent)
            if parent_node is None:
                return 409

            content = b""
            more_body = True
            while more_body:
                request_data: HTTPRequestEvent = await request.receive()  # type: ignore
                more_body = request_data.get("more_body")

                content += request_data.get("body", b"")

            if node is None:
                self.fs.add_node(
                    request.dist_src_path, dst_node_parent=parent_node, content=content
                )
            else:
                node.update_content(content)

            return 201

    async def _do_copy(self, request: DAVRequest) -> int:
        def success_return() -> int:
            if request.overwrite:
                return 204
            else:
                return 201

        async with self.fs_lock:
            src_node = self.fs.get_node(request.dist_src_path)
            if src_node is None:
                return 403
            dst_node_parent = self.fs.get_node(request.dist_dst_path.parent)
            if dst_node_parent is None:
                return 409
            if self.fs.has_node(request.dist_dst_path) and not request.overwrite:
                return 412

            # below ---
            # overwrite or dst_member is None
            if self.fs.copy_node(
                src_node=src_node,
                dst_path=request.dist_dst_path,
                dst_node_parent=dst_node_parent,
                depth=request.depth,
                overwrite=request.overwrite,
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
            dst_node_parent = self.fs.get_node(request.dist_dst_path.parent)
            if dst_node_parent is None:
                return 400
            src_node = self.fs.get_node(request.dist_src_path)
            if src_node is None:
                return 403
            src_node_parent = self.fs.get_node(request.dist_src_path.parent)
            if src_node_parent is None:
                return 409

            if self.fs.has_node(request.dist_dst_path) and not request.overwrite:
                return 412

            if self.fs.move_node(
                src_node=src_node,
                src_node_parent=src_node_parent,
                dst_path=request.dist_dst_path,
                dst_node_parent=dst_node_parent,
                overwrite=request.overwrite,
            ):
                return success_return()

            raise
