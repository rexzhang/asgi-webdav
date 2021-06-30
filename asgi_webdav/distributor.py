from typing import Optional
import re
from dataclasses import dataclass
from copy import copy
from logging import getLogger

from asgi_webdav import __version__
from asgi_webdav.constants import (
    DAVMethod,
    DAVPath,
    DAVDepth,
    DAVTime,
    DIR_BROWSER_MACOS_IGNORE_RULES,
    DIR_BROWSER_WINDOWS_IGNORE_RULES,
    DIR_BROWSER_SYNOLOGY_IGNORE_RULES,
)
from asgi_webdav.config import get_config
from asgi_webdav.request import DAVRequest

from asgi_webdav.provider.dev_provider import DAVProvider
from asgi_webdav.provider.file_system import FileSystemProvider
from asgi_webdav.provider.memory import MemoryProvider
from asgi_webdav.property import DAVProperty
from asgi_webdav.response import DAVResponse
from asgi_webdav.helpers import empty_data_generator, is_browser_user_agent


logger = getLogger(__name__)


_CONTENT_TEMPLATE = """<!DOCTYPE html>
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
<body>
  <header>
    <h1>Index of <small>{}</small></h1>
  </header>
  <hr>
  <main>
  <table>
  <thead>
    <tr>
    <th class="align-left">Name</th><th class="align-left">Type</th>
    <th class="align-right">Size</th><th class="align-right">Last modified</th>
    </tr>
  </thead>
  <tbody>{}</tbody>
  </table>
  </main>
  <hr>
  <footer>
    <a href="https://rexzhang.github.io/asgi-webdav">ASGI WebDAV: v{}</a>,
    <small>
    current time: {},
    <a href="https://github.com/rexzhang/asgi-webdav/issues">report issue</a>
    </small>
  </footer>
</body>
</html>"""

_CONTENT_TBODY_DIR_TEMPLATE = """<tr><td><a href="{}"><b>{}<b></a></td><td>{}</td>
<td class="align-right">{}</td><td class="align-right">{}</td></tr>"""
_CONTENT_TBODY_FILE_TEMPLATE = """<tr><td><a href="{}">{}</a></td><td>{}</td>
<td class="align-right">{}</td><td class="align-right">{}</td></tr>"""


@dataclass
class PrefixProviderInfo:
    prefix: DAVPath
    prefix_weight: int
    provider: DAVProvider
    home_dir: bool = False
    readonly: bool = False  # TODO impl

    def __str__(self):
        return "{} => {}".format(self.prefix, self.provider)


class DAVDistributor:
    prefix_provider_mapping = list()

    def __init__(self):
        config = get_config()

        # init prefix => provider
        for pm in config.provider_mapping:
            if pm.uri.startswith("file://"):
                provider_factory = FileSystemProvider

            elif pm.uri.startswith("memory://"):
                provider_factory = MemoryProvider

            else:
                raise

            provider = provider_factory(
                prefix=DAVPath(pm.prefix),
                uri=pm.uri,
                home_dir=pm.home_dir,
            )
            ppi = PrefixProviderInfo(
                prefix=DAVPath(pm.prefix),
                prefix_weight=len(pm.prefix),
                provider=provider,
                home_dir=pm.home_dir,
            )
            self.prefix_provider_mapping.append(ppi)
            logger.info("Mapping Prefix: {}".format(ppi))

        self.prefix_provider_mapping.sort(
            key=lambda x: getattr(x, "prefix_weight"), reverse=True
        )

        # init dir browser config
        self.dir_browser_config = config.dir_browser

    def match_provider(self, request: DAVRequest) -> Optional[DAVProvider]:
        weight = None
        provider = None

        # match provider
        for ppi in self.prefix_provider_mapping:
            if not request.src_path.startswith(ppi.prefix):
                continue

            if weight is None:  # or ppm.weight < weight:
                weight = ppi.prefix_weight
                provider = ppi.provider
                break  # self.prefix_provider_mapping is sorted!

        if weight is None:
            return None

        return provider

    async def distribute(self, request: DAVRequest) -> DAVResponse:
        # match provider
        provider = self.match_provider(request)
        if provider is None:
            # TODO
            raise

        # check permission
        if not provider.home_dir:
            paths = [request.src_path]
            if isinstance(request.dst_path, DAVPath):
                paths.append(request.dst_path)

            if not request.user.check_paths_permission(paths):
                # not allow
                logger.debug(request)
                return DAVResponse(status=403)

        # update request distribute information
        request.update_distribute_info(provider.prefix)

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

        return response

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
        response = DAVResponse(status=207, data=message)
        return response

    async def _do_propfind(
        self, request: DAVRequest, provider: DAVProvider
    ) -> dict[DAVPath, DAVProperty]:
        dav_properties = await provider.do_propfind(request)

        # remove disallow item in base path
        for path in list(dav_properties.keys()):
            if not request.user.check_paths_permission([path]):
                dav_properties.pop(path)

        if request.depth != DAVDepth.d0:
            for child_provider in self.get_depth_1_child_provider(request.src_path):
                child_request = copy(request)
                if request.depth == DAVDepth.d1:
                    child_request.depth = DAVDepth.d0
                elif request.depth == DAVDepth.infinity:
                    child_request.depth = DAVDepth.d1  # TODO support infinity

                child_request.src_path = child_provider.prefix
                child_request.update_distribute_info(child_provider.prefix)
                child_dav_properties = await child_provider.do_propfind(child_request)

                if not child_provider.home_dir:
                    # remove disallow item in child provider path
                    for path in list(child_dav_properties.keys()):
                        if not request.user.check_paths_permission([path]):
                            child_dav_properties.pop(path)

                dav_properties.update(child_dav_properties)

        return dav_properties

    async def do_get(self, request: DAVRequest, provider: DAVProvider) -> DAVResponse:
        http_status, property_basic_data, data = await provider.do_get(request)
        if http_status != 200:
            # TODO bug
            return DAVResponse(http_status)

        if data is not None:
            headers = property_basic_data.get_get_head_response_headers()
            return DAVResponse(
                200,
                headers=headers,
                data=data,
                data_length=property_basic_data.content_length,
            )

        if data is None and (
            not self.dir_browser_config.enable
            or not is_browser_user_agent(request.headers.get(b"user-agent"))
        ):
            headers = property_basic_data.get_get_head_response_headers()
            data = empty_data_generator()
            return DAVResponse(200, headers=headers, data=data, data_length=0)

        # response dir browser content
        new_request = copy(request)
        new_request.change_from_get_to_propfind_d1_for_dir_browser()

        dav_properties = await self._do_propfind(new_request, provider)
        content = self._create_dir_browser_content(request.src_path, dav_properties)

        property_basic_data.content_type = "text/html"
        property_basic_data.content_length = len(content)

        headers = property_basic_data.get_get_head_response_headers()
        return DAVResponse(
            200,
            headers=headers,
            data=content,
            data_length=property_basic_data.content_length,
        )

    def _create_dir_browser_content(
        self, root_path: DAVPath, dav_properties: dict[DAVPath, DAVProperty]
    ) -> bytes:
        if root_path.count == 0:
            tbody_parent = str()
        else:
            tbody_parent = _CONTENT_TBODY_DIR_TEMPLATE.format(
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
            if self.is_ignore_in_dir_browser(basic_data.display_name):
                continue

            if basic_data.is_collection:
                tbody_dir += _CONTENT_TBODY_DIR_TEMPLATE.format(
                    dav_path.raw,
                    basic_data.display_name,
                    basic_data.content_type,
                    "-",
                    basic_data.last_modified.ui_display(),
                )
            else:
                tbody_file += _CONTENT_TBODY_FILE_TEMPLATE.format(
                    dav_path.raw,
                    basic_data.display_name,
                    basic_data.content_type,
                    f"{basic_data.content_length:,}",
                    basic_data.last_modified.ui_display(),
                )

        content = _CONTENT_TEMPLATE.format(
            root_path.raw,
            root_path.raw,
            tbody_parent + tbody_dir + tbody_file,
            __version__,
            DAVTime().ui_display(),
        )
        return content.encode("utf-8")

    def is_ignore_in_dir_browser(self, filename: str) -> bool:
        # TODO merge regex at init
        if len(self.dir_browser_config.user_ignore_rule) >= 1:
            if re.match(self.dir_browser_config.user_ignore_rule, filename):
                return True

        if self.dir_browser_config.enable_macos_ignore_rules:
            if re.match(DIR_BROWSER_MACOS_IGNORE_RULES, filename):
                return True

        if self.dir_browser_config.enable_windows_ignore_rules:
            if re.match(DIR_BROWSER_WINDOWS_IGNORE_RULES, filename):
                return True

        if self.dir_browser_config.enable_synology_ignore_rules:
            if re.match(DIR_BROWSER_SYNOLOGY_IGNORE_RULES, filename):
                return True

        return False
