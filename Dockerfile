FROM python:3.13-alpine

ARG BUILD_DEV
ENV TZ="Asia/Shanghai"
ENV UID=1000
ENV GID=1000
ENV WEBDAV_HOST="0.0.0.0"
ENV WEBDAV_PORT="8000"
ENV WEBDAV_CONFIGFILE="/data/webdav.json"
ENV WEBDAV_LOGGING_LEVEL="INFO"

RUN if [ "$BUILD_DEV" = "rex" ]; then echo "Change depends" \
    && pip config set global.index-url https://proxpi.h.rexzhang.com/index/ \
    && pip config set install.trusted-host proxpi.h.rexzhang.com \
    && sed -i 's/dl-cdn.alpinelinux.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apk/repositories \
    ; fi

COPY docker /app
COPY requirements.d /app/requirements.d

RUN \
    # install python depends ---
    apk add --no-cache --virtual .build-deps build-base libffi-dev \
    # --- LDAP
    openldap-dev \
    # --- WebHDFS
    krb5-dev \
    # --- build & install
    && pip install --no-cache-dir -r /app/requirements.d/docker.txt \
    # --- cleanup
    && apk del .build-deps \
    && rm -rf /root/.cache \
    && find /usr/local/lib/python*/ -type f -name '*.py[cod]' -delete \
    && find /usr/local/lib/python*/ -type d -name "__pycache__" -delete \
    # LDAP client's depends ---
    && apk add --no-cache libsasl libldap \
    # create non-root user ---
    && apk add --no-cache shadow su-exec \
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

COPY asgi_webdav /app/asgi_webdav

WORKDIR /app
VOLUME /data
EXPOSE 8000

CMD [ "/app/entrypoint.sh" ]

LABEL org.opencontainers.image.title="ASGI WebDAV Server"
LABEL org.opencontainers.image.authors="Rex Zhang"
LABEL org.opencontainers.image.url="https://hub.docker.com/repository/docker/ray1ex/asgi-webdav"
LABEL org.opencontainers.image.source="https://github.com/rexzhang/asgi-webdav"
