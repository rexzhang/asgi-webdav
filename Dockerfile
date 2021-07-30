FROM python:3-slim

# ---------- for develop
#RUN pip config set global.index-url http://host.docker.internal:3141/root/pypi/+simple/ \
#    && pip config set install.trusted-host host.docker.internal
# ----------

COPY asgi_webdav /app/asgi_webdav
COPY requirements /app/requirements

RUN pip install --no-cache-dir -r /app/requirements/docker.txt

WORKDIR /app
EXPOSE 80

VOLUME /data

CMD python -m asgi_webdav --host 0.0.0.0 --port 80 --in-docker-container

LABEL org.opencontainers.image.title="ASGI WebDAV Server"
LABEL org.opencontainers.image.authors="Rex Zhang"
LABEL org.opencontainers.image.url="https://hub.docker.com/repository/docker/ray1ex/asgi-webdav"
LABEL org.opencontainers.image.source="https://github.com/rexzhang/asgi-webdav"
