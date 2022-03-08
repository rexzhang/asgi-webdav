# Multi-Account and Home Directory

## config file
`/your/data/webdav.json`

```json
{
    "account_mapping": [
        {
            "username": "user_all",
            "password": "pw1",
            "permissions": [
                "+"
            ]
        },
        {
            "username": "user_a",
            "password": "pw2",
            "permissions": [
                "+^/$",
                "+^/share",
                "-^/share/no_a"
            ]
        },
        {
            "username": "user_b",
            "password": "pw3",
            "permissions": [
                "+^/$",
                "+^/share",
                "-^/share/no_b"
            ]
        },
        {
            "username": "guest",
            "password": "pw4",
            "permissions": []
        }
    ],  
    "provider_mapping": [
        {
            "prefix": "/",
            "uri": "file:///data/root"
        },
        {
            "prefix": "/temp1",
            "uri": "memory:///"
        },
        {
            "prefix": "/temp2",
            "uri": "memory:///"
        },
        {
            "prefix": "/~",
            "uri": "file:///data/homes",
            "home_dir": true
        }
    ]
}
```

## docker command
```
docker run --restart always -p 0.0.0.0:8000:8000 \
  -v /your/data:/data -v /your/data/homes:/data/homes \
  --name asgi-webdav ray1ex/asgi-webdav
```

## URL/path mapping table

| user     | URL      | path in docker container | path in host                  |
|----------|----------|--------------------------|-------------------------------|
| All      | `/`      | `/data/root`             | `/your/data/root`             |
| All      | `/share` | `/data/root/share`       | `/your/data/root/share`       |
| All      | `/temp1` | memory area #1           |                               |
| All      | `/temp2` | memory area #2           |                               |
| `user_a` | `/~`     | `/data/homes/user_a`     | `/your/data/homes/user_a`     |
| `user_a` | `/~/sub` | `/data/homes/user_a/sub` | `/your/data/homes/user_a/sub` |
| `user_b` | `/~`     | `/data/homes/user_b`     | `/your/data/homes/user_b`     |
| `user_b` | `/~/sub` | `/data/homes/user_b/sub` | `/your/data/homes/user_b/sub` |

## account permission

| username          | `user_all` | `user_a` | `user_b` | `guest` |
|-------------------|------------|----------|----------|---------|
| password          | `pw1`      | `pw2`    | `pw3`    | `pw4`   |
| URL `/~`          | Allow      | Allow    | Allow    | Allow   |
| URL `/`           | Allow      | Allow    | Allow    | Deny    |
| URL `/share`      | Allow      | Allow    | Allow    | Deny    |
| URL `/share/no_a` | Allow      | Deny     | Allow    | Deny    |
| URL `/share/no_b` | Allow      | Allow    | Deny     | Deny    |
| other URL         | Allow      | Deny     | Deny     | Deny    |
