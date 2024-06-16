from collections.abc import Callable
from dataclasses import dataclass

from asgi_webdav.request import DAVRequest
from asgi_webdav.response import DAVResponse


@dataclass
class PageURL:
    path: str
    view: Callable
    require_user: bool = True
    require_admin: bool = False


class PageResponseBase:
    pass


class PageResponseHTML(PageResponseBase):
    pass


class PageResponseJSON(PageResponseBase):
    pass


class PageResponseRedirect(PageResponseBase):
    pass


"""
HttpResponseBadRequest
HttpResponseNotAllowed
HttpResponseNotFound
HttpResponseForbidden
HttpResponseServerError
"""


class PageView:
    async def __call__(self, request: DAVRequest) -> DAVResponse:
        status, content = self._get_response(request)
        return DAVResponse(status=status, content=content.encode("utf-8"))

    def _get_response(self, request: DAVRequest) -> (int, str):
        raise NotImplementedError()


class PageTemplateView(PageView):
    pass


class PageEntry:
    urls: list[PageURL]

    def __init__(self):
        self._data = dict()
        for url_obj in self.urls:
            self._data[url_obj.path] = url_obj

    async def enter(self, request: DAVRequest) -> DAVResponse:
        url_obj = self._data.get(request.path.raw)
        if url_obj is None:
            return DAVResponse(404)

        if url_obj.require_user and request.user is None:
            return DAVResponse(403, content=b"Requires user privileges")

        if url_obj.require_admin and not request.user.admin:
            return DAVResponse(403, content=b"Requires administrator privileges")

        return await url_obj.view(request)
