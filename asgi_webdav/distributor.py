from typing import Optional
from dataclasses import dataclass
from copy import copy
from logging import getLogger

from asgi_webdav import __version__
from asgi_webdav.constants import (
    DAVMethod,
    DAVPath,
    DAVDepth,
    DAVTime,
)
from asgi_webdav.config import Config
from asgi_webdav.request import DAVRequest
from asgi_webdav.provider.dev_provider import DAVProvider
from asgi_webdav.provider.file_system import FileSystemProvider
from asgi_webdav.provider.memory import MemoryProvider
from asgi_webdav.property import DAVProperty
from asgi_webdav.response import DAVResponse
from asgi_webdav.helpers import (
    empty_data_generator,
    get_data_generator_from_content,
)

logger = getLogger(__name__)


_DIR_BROWSER_CONTENT_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Index of {}</title>
  <style>
    table {{ table-layout: auto;width: 100%; }}
    tbody tr:nth-of-type(even) {{ background-color: #f3f3f3; }}
    .align-left {{ text-align: left; }}
    .align-right {{ text-align: right; }}
  </style>
</head>
<body >
  <header>
    <h1>Index of <small>{}</small></h1> 
  </header>
  <hr>
  <main>
  <table>
  <thead>
    <tr><th class="align-left">Name</th><th class="align-left">Type</th><th class="align-right">Size</th><th class="align-right">Last modified</th></tr>
  </thead>
  <tbody>{}</tbody>
  </table>
  </main>
  <hr>
  <footer>
    <small><a href="https://github.com/rexzhang/asgi-webdav">ASGI WebDAV v{}</a> - {}</small>
  </footer>
</body>
</html>"""

_DIR_BROWSER_CONTENT_TBODY_DIR_TEMPLATE = '<tr><td><a href="{}"><b>{}<b></a></td><td>{}</td><td class="align-right">{}</td><td class="align-right">{}</td></tr>'
_DIR_BROWSER_CONTENT_TBODY_FILE_TEMPLATE = '<tr><td><a href="{}">{}</a></td><td>{}</td><td class="align-right">{}</td><td class="align-right">{}</td></tr>'


@dataclass
class PrefixProviderMapping:
    prefix: DAVPath
    weight: int
    provider: DAVProvider
    readonly: bool = False  # TODO impl

    def __repr__(self):
        return "Mapping: {} => {}".format(self.prefix, self.provider)


class DAVDistributor:
    def __init__(self, config: Config):
        self.prefix_provider_mapping = list()
        for pm in config.provider_mapping:
            if pm.uri.startswith("file://"):
                provider = FileSystemProvider(
                    dist_prefix=DAVPath(pm.prefix), root_path=pm.uri[7:]
                )

            elif pm.uri.startswith("memory://"):
                provider = MemoryProvider(dist_prefix=DAVPath(pm.prefix))

            else:
                raise

            ppm = PrefixProviderMapping(
                prefix=DAVPath(pm.prefix), weight=len(pm.prefix), provider=provider
            )
            self.prefix_provider_mapping.append(ppm)
            logger.info(ppm)

        self.prefix_provider_mapping.sort(
            key=lambda x: getattr(x, "weight"), reverse=True
        )

        self.display_dir_browser = config.display_dir_browser

    def match_provider(self, request: DAVRequest) -> Optional[DAVProvider]:
        weight = None
        provider = None

        # match provider
        for ppm in self.prefix_provider_mapping:
            if not request.src_path.startswith(ppm.prefix):
                continue

            if weight is None:  # or ppm.weight < weight:
                weight = ppm.weight
                provider = ppm.provider
                break  # self.prefix_provider_mapping is sorted!

        if weight is None:
            return None

        return provider

    async def distribute(self, request: DAVRequest):
        provider = self.match_provider(request)
        if provider is None:
            raise

        # update request distribute information
        request.update_distribute_info(provider.dist_prefix)

        # parser body
        await request.parser_body()
        logger.debug(request)

        # call method
        # high freq interface ---
        if request.method == DAVMethod.HEAD:
            response = await provider.do_head(request)

        elif request.method == DAVMethod.GET:
            response = await self.do_get(request, provider)

        elif request.method == DAVMethod.PROPFIND:
            response = await self.do_propfind(request, provider)

        elif request.method == DAVMethod.PROPPATCH:
            response = await provider.do_proppatch(request)

        elif request.method == DAVMethod.LOCK:
            response = await provider.do_lock(request)

        elif request.method == DAVMethod.UNLOCK:
            response = await provider.do_unlock(request)

        # low freq interface ---
        elif request.method == DAVMethod.MKCOL:
            response = await provider.do_mkcol(request)

        elif request.method == DAVMethod.DELETE:
            response = await provider.do_delete(request)

        elif request.method == DAVMethod.PUT:
            response = await provider.do_put(request)

        elif request.method == DAVMethod.COPY:
            response = await provider.do_copy(request)

        elif request.method == DAVMethod.MOVE:
            response = await provider.do_move(request)

        # other interface ---
        elif request.method == DAVMethod.OPTIONS:
            response = await provider.get_options(request)

        else:
            raise Exception("{} is not support method".format(request.method))

        logger.debug(response)
        await response.send_in_one_call(request.send)
        return

    def get_depth_1_child_provider(self, prefix: DAVPath) -> list[DAVProvider]:
        providers = list()
        for ppm in self.prefix_provider_mapping:
            if ppm.prefix.startswith(prefix):
                if ppm.prefix.get_child(prefix).count == 1:
                    providers.append(ppm.provider)

        return providers

    async def do_propfind(
        self, request: DAVRequest, provider: DAVProvider
    ) -> DAVResponse:
        if not request.body_is_parsed_success:
            # TODO ??? 40x?
            return DAVResponse(400)

        dav_properties = await self._do_propfind(request, provider)
        if len(dav_properties) == 0:
            return DAVResponse(404)

        message = await provider.create_propfind_response(request, dav_properties)
        response = DAVResponse(status=207, message=message)
        return response

    async def _do_propfind(
        self, request: DAVRequest, provider: DAVProvider
    ) -> dict[DAVPath, DAVProperty]:
        dav_properties = await provider.do_propfind(request)

        if request.depth != DAVDepth.d0:
            for child_provider in self.get_depth_1_child_provider(request.src_path):
                child_request = copy(request)
                if request.depth == DAVDepth.d1:
                    child_request.depth = DAVDepth.d0
                elif request.depth == DAVDepth.infinity:
                    child_request.depth = DAVDepth.d1  # TODO support infinity

                child_request.src_path = child_provider.dist_prefix
                child_request.update_distribute_info(child_provider.dist_prefix)
                child_dav_properties = await child_provider.do_propfind(child_request)
                dav_properties.update(child_dav_properties)

        return dav_properties

    async def do_get(self, request: DAVRequest, provider: DAVProvider) -> DAVResponse:
        http_status, property_basic_data, data = await provider.do_get(request)
        if http_status != 200:
            # TODO bug
            return DAVResponse(http_status)

        if data is not None:
            headers = property_basic_data.get_get_head_response_headers()
            return DAVResponse(200, headers=headers, data=data)

        if data is None and not self.display_dir_browser:
            headers = property_basic_data.get_get_head_response_headers()
            data = empty_data_generator()
            return DAVResponse(200, headers=headers, data=data)

        # data is None and self.display_dir_browser
        new_request = copy(request)
        new_request.change_from_get_to_propfind_d1_for_dir_browser()

        dav_properties = await self._do_propfind(new_request, provider)
        content = self._create_dir_browser_content(request.src_path, dav_properties)

        property_basic_data.content_type = "text/html"
        property_basic_data.content_length = len(content)

        headers = property_basic_data.get_get_head_response_headers()
        data = get_data_generator_from_content(content)
        return DAVResponse(200, headers=headers, data=data)

    @staticmethod
    def _create_dir_browser_content(
        root_path: DAVPath, dav_properties: dict[DAVPath, DAVProperty]
    ) -> bytes:
        if root_path.count == 0:
            tbody_parent = str()
        else:
            tbody_parent = _DIR_BROWSER_CONTENT_TBODY_DIR_TEMPLATE.format(
                root_path.parent, "..", "-", "-", "-"
            )

        tbody_dir = str()
        tbody_file = str()
        dav_path_list = list(dav_properties.keys())
        dav_path_list.sort()
        for dav_path in dav_path_list:
            basic_data = dav_properties[dav_path].basic_data
            if dav_path == root_path:
                continue
            if basic_data.display_name.startswith("._"):
                continue
            if basic_data.display_name == ".DS_Store":
                continue

            if basic_data.is_collection:
                tbody_dir += _DIR_BROWSER_CONTENT_TBODY_DIR_TEMPLATE.format(
                    dav_path.raw,
                    basic_data.display_name,
                    basic_data.content_type,
                    "-",
                    basic_data.last_modified.iso_8601(),
                )
            else:
                tbody_file += _DIR_BROWSER_CONTENT_TBODY_FILE_TEMPLATE.format(
                    dav_path.raw,
                    basic_data.display_name,
                    basic_data.content_type,
                    f"{basic_data.content_length:,}",
                    basic_data.last_modified.iso_8601(),
                )

        content = _DIR_BROWSER_CONTENT_TEMPLATE.format(
            root_path.raw,
            root_path.raw,
            tbody_parent + tbody_dir + tbody_file,
            __version__,
            DAVTime().iso_8601(),
        )
        return content.encode("utf-8")
