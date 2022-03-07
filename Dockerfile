FROM python:3.10-alpine

ARG ENV
RUN if [ "$ENV" = "rex" ]; then echo "Change depends" \
    && pip config set global.index-url http://192.168.200.21:3141/root/pypi/+simple \
    && pip config set install.trusted-host 192.168.200.21 \
    && sed -i 's/dl-cdn.alpinelinux.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apk/repositories \
    ; fi

COPY requirements /app/requirements
COPY asgi_webdav /app/asgi_webdav
COPY docker /app

ENV UID=1000
ENV GID=1000

RUN \
    # install depends
    apk add --no-cache --virtual .build-deps build-base libffi-dev openldap-dev \
    && pip install --no-cache-dir -r /app/requirements/docker.txt \
    && apk del .build-deps \
    && find /usr/local/lib/python*/ -type f -name '*.py[cod]' -delete \
    # LDAP client's depends
    && apk add libsasl libldap \
    # create non-root user
    && apk add --no-cache shadow \
    && addgroup -S -g $GID prisoner \
    && adduser -S -D -G prisoner -u $UID prisoner \
    # fix libexpat bug:
    #   out of memory: line 1, column 0
    #   https://bugs.launchpad.net/ubuntu/+source/python-xmltodict/+bug/1961800
    && apk add 'expat>2.4.7' \
    # prepare
    && mkdir /data

WORKDIR /app
VOLUME /data
EXPOSE 8000

ENTRYPOINT /app/entrypoint.sh

LABEL org.opencontainers.image.title="ASGI WebDAV Server"
LABEL org.opencontainers.image.authors="Rex Zhang"
LABEL org.opencontainers.image.url="https://hub.docker.com/repository/docker/ray1ex/asgi-webdav"
LABEL org.opencontainers.image.source="https://github.com/rexzhang/asgi-webdav"
