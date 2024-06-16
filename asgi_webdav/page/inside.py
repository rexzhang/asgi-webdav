from jinja2 import DictLoader, Environment

from asgi_webdav.log import get_log_messages
from asgi_webdav.page.base import PageEntry, PageURL, PageView
from asgi_webdav.request import DAVRequest

jinja_template_mapping = {
    "info.html": """System Info:
Session Info:
User: {{ username }}
"""
}
env = Environment(loader=DictLoader(jinja_template_mapping))


class IndexView(PageView):
    def _get_response(self, request: DAVRequest) -> (int, str):
        return 200, '<a href="/_/admin/logging">Logging page</a>'


class InfoView(PageView):
    def _get_response(self, request: DAVRequest) -> (int, str):
        return 200, env.get_template("info.html").render(username=request.user.username)


class LoggingView(PageView):
    def _get_response(self, request: DAVRequest) -> (int, str):
        data = ""
        for message in get_log_messages():
            data += message + "<br>"
        return 200, data


urls = [
    PageURL("/_", IndexView()),
    PageURL("/_/info", InfoView(), require_admin=True),
    PageURL("/_/admin/logging", LoggingView()),
]


class InsidePage(PageEntry):
    urls = urls
