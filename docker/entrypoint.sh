#!/bin/sh

## set non-root user
usermod -o -u "$UID" runner
groupmod -o -g "$GID" runner

echo "
------------------------
User uid: $(id -u runner)
User gid: $(id -g runner)
------------------------
"

chown -R runner:runner /data

# run server
su runner -s /app/asgi-webdav.py
python
