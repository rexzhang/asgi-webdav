from copy import copy
from dataclasses import dataclass
from logging import getLogger

from asgi_webdav import __version__
from asgi_webdav.config import Config
from asgi_webdav.constants import DAVDepth, DAVMethod, DAVPath, DAVTime
from asgi_webdav.exception import ProviderInitException
from asgi_webdav.helpers import empty_data_generator, is_browser_user_agent
from asgi_webdav.property import DAVProperty
from asgi_webdav.provider.dev_provider import DAVProvider
from asgi_webdav.provider.file_system import FileSystemProvider
from asgi_webdav.provider.memory import MemoryProvider
from asgi_webdav.request import DAVRequest
from asgi_webdav.response import DAVHideFileInDir, DAVResponse, DAVResponseType

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
        return f"{self.prefix} => {self.provider}"


class WebDAV:
    prefix_provider_mapping: list = list()

    def __init__(self, config: Config):
        # init prefix => provider
        for pm in config.provider_mapping:
            if pm.uri.startswith("file://"):
                provider_factory = FileSystemProvider

            elif pm.uri.startswith("memory://"):
                provider_factory = MemoryProvider

            else:
                raise

            provider = provider_factory(
                config=config,
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
            logger.info(f"Mapping Prefix: {ppi}")

        self.prefix_provider_mapping.sort(
            key=lambda x: getattr(x, "prefix_weight"), reverse=True
        )

        # init dir browser config
        self.enable_dir_browser = config.enable_dir_browser

        # init hide file in dir
        self._hide_file_in_dir = DAVHideFileInDir(config)

    def match_provider(self, request: DAVRequest) -> DAVProvider | None:
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
            raise ProviderInitException(
                f"Please mapping [{request.path}] to one provider"
            )

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
            raise Exception(f"{request.method} is not support method")

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

        match len(dav_properties):
            case 0:
                return DAVResponse(404)
            case _:
                response_status = 207

        message = await provider.create_propfind_response(request, dav_properties)
        response = DAVResponse(
            status=response_status, content=message, response_type=DAVResponseType.XML
        )
        return response

    async def _do_propfind_hide_file_in_dir(
        self, request: DAVRequest, data: dict[DAVPath, DAVProperty]
    ) -> dict[DAVPath, DAVProperty]:
        for k in list(data.keys()):
            if await self._hide_file_in_dir.is_match_hide_file_in_dir(
                request.client_user_agent, k.name
            ):
                data.pop(k)

        return data

    async def _do_propfind(
        self, request: DAVRequest, provider: DAVProvider
    ) -> dict[DAVPath, DAVProperty]:
        dav_properties = await provider.do_propfind(request)
        if provider.home_dir:
            return await self._do_propfind_hide_file_in_dir(request, dav_properties)

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

        return await self._do_propfind_hide_file_in_dir(request, dav_properties)

    async def do_get(self, request: DAVRequest, provider: DAVProvider) -> DAVResponse:
        http_status, property_basic_data, data = await provider.do_get(request)
        if http_status not in {200, 206}:
            # TODO bug
            return DAVResponse(http_status)

        # is a file
        if data is not None:
            headers = property_basic_data.get_get_head_response_headers()
            if provider.support_content_range:
                headers.update(
                    {
                        b"Accept-Ranges": b"bytes",
                    }
                )
                content_range_start = request.content_range_start

            else:
                content_range_start = None

            return DAVResponse(
                http_status,
                headers=headers,
                content=data,
                content_length=property_basic_data.content_length,
                content_range_start=content_range_start,
            )

        # is a dir
        if data is None and (
            not self.enable_dir_browser
            or not is_browser_user_agent(request.headers.get(b"user-agent"))
        ):
            headers = property_basic_data.get_get_head_response_headers()
            data = empty_data_generator()
            return DAVResponse(200, headers=headers, content=data, content_length=0)

        # response dir browser content
        new_request = copy(request)
        new_request.change_from_get_to_propfind_d1_for_dir_browser()

        dav_properties = await self._do_propfind(new_request, provider)
        content = await self._create_dir_browser_content(
            request.client_user_agent, request.src_path, dav_properties
        )

        property_basic_data.content_type = "text/html"
        property_basic_data.content_length = len(content)

        headers = property_basic_data.get_get_head_response_headers()
        return DAVResponse(
            200,
            headers=headers,
            content=content,
            content_length=property_basic_data.content_length,
        )

    async def _create_dir_browser_content(
        self,
        client_user_agent: str,
        root_path: DAVPath,
        dav_properties: dict[DAVPath, DAVProperty],
    ) -> bytes:
        if root_path.count == 0:
            tbody_parent = ""
        else:
            tbody_parent = _CONTENT_TBODY_DIR_TEMPLATE.format(
                root_path.parent, "..", "-", "-", "-"
            )

        tbody_dir = ""
        tbody_file = ""
        dav_path_list = list(dav_properties.keys())
        dav_path_list.sort()
        for dav_path in dav_path_list:
            basic_data = dav_properties[dav_path].basic_data
            if dav_path == root_path:
                continue
            if await self._hide_file_in_dir.is_match_hide_file_in_dir(
                client_user_agent, basic_data.display_name
            ):
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
