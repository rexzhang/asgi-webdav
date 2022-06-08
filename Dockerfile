FROM python:3.10-alpine

ARG ENV
ENV UID=1000
ENV GID=1000

COPY requirements /app/requirements
COPY asgi_webdav /app/asgi_webdav
COPY docker /app

RUN if [ "$ENV" = "dev" ]; then echo "ENV:dev" \
    && pip config set global.index-url http://192.168.200.23:3141/root/pypi/+simple \
    && pip config set install.trusted-host 192.168.200.23 \
    && sed -i 's/dl-cdn.alpinelinux.org/mirrors.ustc.edu.cn/g' /etc/apk/repositories \
    # && sed -i 's/dl-cdn.alpinelinux.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apk/repositories \
    ; else echo "ENV:release" \
    && pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple \
    && sed -i 's/dl-cdn.alpinelinux.org/mirrors.ustc.edu.cn/g' /etc/apk/repositories \
    ; fi \
    # install build's depends ---
    && apk add --no-cache --virtual .build-deps build-base libffi-dev openldap-dev \
    # cryptography depends --- https://cryptography.io/en/37.0.2/installation/
    # gcc musl-dev python3-dev libffi-dev openssl-dev cargo \
    # && mkdir /root/.cargo \
    # && mv /app/cargo.config.toml /root/.cargo/config.toml
    # install python package \
    # && pip install --no-cache-dir -U pip setuptools \
    && pip install --no-cache-dir -r /app/requirements/docker.txt \
    # cleanup ---
    && apk del .build-deps \
    && rm -rf /root/.cargo \
    && rm -rf /root/.cache \
    && find /usr/local/lib/python*/ -type f -name '*.py[cod]' -delete \
    && find /usr/local/lib/python*/ -type d -name "__pycache__" -delete \
    # LDAP client's depends ---
    && apk add --no-cache libsasl libldap \
    # create non-root user ---
    && apk add --no-cache shadow \
    && addgroup -S -g $GID runner \
    && adduser -S -D -G runner -u $UID runner \
    # fix libexpat bug:
    #   out of memory: line 1, column 0
    #   https://bugs.launchpad.net/ubuntu/+source/python-xmltodict/+bug/1961800
    && apk add 'expat>2.4.7' \
    # prepare ---
    && mkdir /data

WORKDIR /app
VOLUME /data
EXPOSE 8000

ENTRYPOINT /app/entrypoint.sh

LABEL org.opencontainers.image.title="ASGI WebDAV Server"
LABEL org.opencontainers.image.authors="Rex Zhang"
LABEL org.opencontainers.image.url="https://hub.docker.com/repository/docker/ray1ex/asgi-webdav"
LABEL org.opencontainers.image.source="https://github.com/rexzhang/asgi-webdav"
