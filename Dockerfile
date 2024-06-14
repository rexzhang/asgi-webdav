FROM python:3.12-alpine

ARG ENV
ENV TZ="Asia/Shanghai"
ENV UID=1000
ENV GID=1000
ENV WEBDAV_LOGGING_LEVEL="INFO"

RUN if [ "$ENV" = "rex" ]; then echo "Change depends" \
    && pip config set global.index-url http://192.168.200.26:13141/root/pypi/+simple \
    && pip config set install.trusted-host 192.168.200.26 \
    && sed -i 's/dl-cdn.alpinelinux.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apk/repositories \
    ; fi

COPY docker /app
COPY requirements /app/requirements
COPY asgi_webdav /app/asgi_webdav

RUN \
    # install build's depends ---
    apk add --no-cache --virtual .build-deps build-base libffi-dev openldap-dev \
    && pip install --no-cache-dir -r /app/requirements/docker.txt \
    # cleanup ---
    && apk del .build-deps \
    && rm -rf /root/.cache \
    && find /usr/local/lib/python*/ -type f -name '*.py[cod]' -delete \
    && find /usr/local/lib/python*/ -type d -name "__pycache__" -delete \
    # LDAP client's depends ---
    && apk add --no-cache libsasl libldap \
    # create non-root user ---
    && apk add --no-cache shadow su-exec\
    && addgroup -S -g $GID runner \
    && adduser -S -D -G runner -u $UID -s /bin/sh runner \
    # support timezone ---
    && apk add --no-cache tzdata \
    # fix libexpat bug:
    #   out of memory: line 1, column 0
    #   https://bugs.launchpad.net/ubuntu/+source/python-xmltodict/+bug/1961800
    && apk add 'expat>2.4.7' \
    # prepare ---
    && mkdir /data

WORKDIR /app
VOLUME /data
EXPOSE 8000

CMD [ "/app/entrypoint.sh" ]

LABEL org.opencontainers.image.title="ASGI WebDAV Server"
LABEL org.opencontainers.image.authors="Rex Zhang"
LABEL org.opencontainers.image.url="https://hub.docker.com/repository/docker/ray1ex/asgi-webdav"
LABEL org.opencontainers.image.source="https://github.com/rexzhang/asgi-webdav"
