#!/bin/sh

## set non-root user
usermod -o -u "$UID" prisoner
groupmod -o -g "$GID" prisoner

echo "
------------------------
User uid: $(id -u prisoner)
User gid: $(id -g prisoner)
------------------------
"

chown -R prisoner:prisoner /data

# run server
su prisoner -s /app/asgi-webdav.py
python
