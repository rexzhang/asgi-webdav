from __future__ import annotations

from copy import copy
from dataclasses import dataclass
from logging import getLogger
from zoneinfo import ZoneInfo

from asgi_webdav import __version__
from asgi_webdav.config import Config, Provider
from asgi_webdav.constants import (
    DAVDepth,
    DAVMethod,
    DAVPath,
    DAVResponseContentType,
    DAVTime,
)
from asgi_webdav.exceptions import DAVException, DAVExceptionProviderInitFailed
from asgi_webdav.helpers import get_timezone, is_browser_user_agent
from asgi_webdav.property import DAVProperty
from asgi_webdav.provider.common import DAVProvider
from asgi_webdav.provider.file_system import FileSystemProvider
from asgi_webdav.provider.memory import MemoryProvider
from asgi_webdav.provider.webhdfs import WebHDFSProvider
from asgi_webdav.request import DAVRequest
from asgi_webdav.response import (
    DAVHideFileInDir,
    DAVResponse,
    DAVResponseMethodNotAllowed,
)

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

_HTTP_PROVIDERS = {p.type: p for p in [WebHDFSProvider]}


@dataclass(slots=True)
class PrefixProviderInfo:
    prefix: DAVPath
    prefix_weight: int
    provider: DAVProvider
    home_dir: bool
    read_only: bool
    ignore_property_extra: bool

    def __str__(self) -> str:
        flag_list = list()
        if self.home_dir:
            flag_list.append("home_dir")
        if self.read_only:
            flag_list.append("read_only")
        if self.ignore_property_extra:
            flag_list.append("ignore_property_extra")

        flag_str = ",".join(flag_list)
        if flag_str:
            flag_str = f" ,[{flag_str}]"

        return f"{self.prefix} ==> {self.provider}{flag_str}"


class WebDAV:
    prefix_provider_mapping: list[PrefixProviderInfo] = list()
    timezone: ZoneInfo

    def __init__(self, config: Config):
        # init prefix => provider
        for p_config in config.provider_mapping:
            try:
                provider_class = self.match_provider_class(p_config)
            except DAVExceptionProviderInitFailed as e:
                logger.error(f"{e}, please check your config, skip!")
                continue

            try:
                provider = provider_class(
                    config=config,
                    prefix=DAVPath(p_config.prefix),
                    uri=p_config.uri,
                    home_dir=p_config.home_dir,
                    read_only=p_config.read_only,
                    ignore_property_extra=p_config.ignore_property_extra,
                )
            except DAVExceptionProviderInitFailed as e:
                logger.error(f"Provider init failed: {p_config}, {e}, skip!")
                continue

            ppi = PrefixProviderInfo(
                prefix=DAVPath(p_config.prefix),
                prefix_weight=len(p_config.prefix),
                provider=provider,
                home_dir=p_config.home_dir,
                read_only=p_config.read_only,
                ignore_property_extra=p_config.ignore_property_extra,
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

        # check environment variable
        try:
            self.timezone = get_timezone()
        except DAVException as e:
            DAVException(f"Please check environment variable: TZ, {e}")

    @staticmethod
    def match_provider_class(
        p_config: Provider,
    ) -> type[DAVProvider]:
        if p_config.uri.startswith("file://"):
            return FileSystemProvider

        elif p_config.uri.startswith("memory://"):
            return MemoryProvider

        elif p_config.uri.startswith("http://") or p_config.uri.startswith("https://"):
            provider_class = _HTTP_PROVIDERS.get(p_config.type)
            if provider_class is None:
                raise DAVExceptionProviderInitFailed(
                    f"Provider not found: {p_config}",
                )

            return provider_class

        raise DAVExceptionProviderInitFailed(f"Provider uri not supported: {p_config}")

    def match_provider(self, request: DAVRequest) -> DAVProvider | None:
        weight = None
        provider = None

        # match provider
        for ppi in self.prefix_provider_mapping:
            if not ppi.prefix.is_parent_of_or_is_self(request.src_path):
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
            message = f"Please mapping [{request.path}] to one provider"
            logger.error(message)
            return DAVResponse(404, content=message.encode())

        # check permission
        if not provider.home_dir:
            paths = [request.src_path]
            if isinstance(request.dst_path, DAVPath):
                paths.append(request.dst_path)

            if not request.user.check_paths_permission(paths):
                # not allow
                logger.debug(request)
                if request.user.anonymous:
                    # is anonymous user
                    return DAVResponse(status=401)
                else:
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
            response = DAVResponseMethodNotAllowed(request.method)

        return response

    def get_depth_1_child_provider(self, prefix: DAVPath) -> list[DAVProvider]:
        providers = list()
        for ppm in self.prefix_provider_mapping:
            if prefix.is_parent_of(ppm.prefix):
                if ppm.prefix.get_child(prefix).parts_count == 1:
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
            status=response_status,
            content=message,
            response_type=DAVResponseContentType.XML,
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

        if request.depth != DAVDepth.ZERO:
            for child_provider in self.get_depth_1_child_provider(request.src_path):
                child_request = copy(request)
                if request.depth == DAVDepth.ONE:
                    child_request.depth = DAVDepth.ZERO
                elif request.depth == DAVDepth.INFINITY:
                    child_request.depth = DAVDepth.ONE  # TODO support infinity

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
        http_status, property_basic_data, body_generator, response_content_range = (
            await provider.do_get(request)
        )
        if http_status not in {200, 206, 416}:
            # TODO bug
            return DAVResponse(http_status)

        if property_basic_data is None:
            raise DAVException(
                f"http_status:{http_status}, property_basic_data is None, please check code base"
            )

        # is a file
        if body_generator is not None:
            headers = property_basic_data.get_get_head_response_headers()
            if response_content_range is None:
                # response the entire file
                return DAVResponse(
                    http_status,
                    headers=headers,
                    content=body_generator,
                    content_length=property_basic_data.content_length,
                    content_range=None,
                    content_range_support=provider.feature.content_range,
                    response_type=DAVResponseContentType.ANY,
                )

            else:
                if http_status == 416:
                    # https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Status/416
                    # file changed, response 416 Range Not Satisfiable
                    return DAVResponse(
                        http_status,
                        headers={
                            b"Content-Range": f"*/{property_basic_data.content_length}".encode()
                        },
                    )

                # response file with range
                return DAVResponse(
                    http_status,
                    headers=headers,
                    content=body_generator,
                    content_length=property_basic_data.content_length,
                    content_range=response_content_range,
                    content_range_support=provider.feature.content_range,
                    response_type=DAVResponseContentType.ANY,
                )

        # is a dir
        if body_generator is None and (
            not self.enable_dir_browser
            or not is_browser_user_agent(request.headers.get(b"user-agent"))
        ):
            headers = property_basic_data.get_get_head_response_headers()
            return DAVResponse(200, headers=headers, content=b"")

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
        if root_path.parts_count == 0:
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
                    basic_data.last_modified.display(self.timezone),
                )
            else:
                tbody_file += _CONTENT_TBODY_FILE_TEMPLATE.format(
                    dav_path.raw,
                    basic_data.display_name,
                    basic_data.content_type,
                    f"{basic_data.content_length:,}",
                    basic_data.last_modified.display(self.timezone),
                )

        content = _CONTENT_TEMPLATE.format(
            root_path.raw,
            root_path.raw,
            tbody_parent + tbody_dir + tbody_file,
            __version__,
            DAVTime().display(self.timezone),
        )
        return content.encode("utf-8")
