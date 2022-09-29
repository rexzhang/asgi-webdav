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
su runner -c "python -m asgi_webdav -H 0.0.0.0 -c /data/webdav.json --logging-no-display-datetime --logging-no-use-colors"

# for dev
if [ "$DEV" = "true" ]; then python; fi
