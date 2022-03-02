# 简明手册(docker)

## 安装
下载 docker 镜像
```
docker pull ray1ex/asgi-webdav:latest
```

## 基本配置
### 一、零配置体验，全默认配置启动

#### 创建并启动容器

```
docker run --restart always -p 0.0.0.0:8000:8000 \
  -v /your/data:/data \
  --name asgi-webdav ray1ex/asgi-webdav
```

#### 配置说明

因为在 `/your/data` 下没有 `webdav.json` 文件，所以会以全默认配置启动。根目录对应`/your/data`；只有一个账号，用户名`username`，密码`password`，权限无限制。

### 二、自定义/多账号

#### 创建配置文件

创建文件 `/your/data/webdav.json`，修改文件内容如下

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
            "username": "user_litmus",
            "password": "pw2",
            "permissions": [
                "+^/$",
                "+^/litmus",
                "-^/litmus/other"
            ]
        },
        {
            "username": "guest",
            "password": "pw3",
            "permissions": []
        }
    ]
}
```

> 文件格式为 JSON；在最后一个大括弧和方括弧后面不能有逗号； 其中 `permissions` 列表内的格式为正则表达式

#### 配置说明

重启 docker 容器后生效，重启后生效三个账号：

- `user_all` 的密码为 `pw1`，权限为允许访问所有 URL
- `user_litmus`的密码为`pw2`
    - 允许访问
        - URL `/`
        - URL`/litmus`以及其子目录
    - 禁止访问
        - URL`/litmus/other`以及其子目录
- `guest`的密码为`pw3`，无任何 URL 访问权限

>  权限规则不分读写；对某个 URL 有权限，既表示对此 URL 下的文件和子路径均有读写权限，并可列出此路径下所有成员

### 三、更复杂的共享目录设置/映射

#### 修改配置文件

文件 `/your/data/webdav.json` 内容如下

```json
{
    "account_mapping": [
        {
            "username": "username",
            "password": "password",
            "permissions": [
                "+"
            ]
        }
    ],
    "provider_mapping": [
        {
            "prefix": "/",
            "uri": "file:///data/root"
        },
        {
            "prefix": "/litmus",
            "uri": "memory:///"
        },
        {
            "prefix": "/litmus/fs",
            "uri": "file:///data/other"
        },
        {
            "prefix": "/litmus/memory",
            "uri": "memory:///"
        }
    ]
}
```

#### 创建并启动容器

```
docker run --restart always -p 0.0.0.0:8000:8000 \
  -v /your/data:/data -v /your/data/other:/data/other \
  --name asgi-webdav ray1ex/asgi-webdav
```

#### 配置说明

共享目录路径对应表

| HTTP 路径          | Docker 容器内路径  | 宿主机器路径             |
|------------------|---------------|--------------------|
| `/`              | `/data/root`  | `/your/data/root`  |
| `/litmus`        | 内存区域A         |                    |
| `/litmus/fs`     | `/data/other` | `/your/data/other` |
| `/litmus/memory` | 内存区域B         |                    |

> 如果不在宿主机上创建 `/your/data/root`这个路径，系统也可以工作；但访问 `/` 这个 URL 只会得到一个 404 错误

### 四、家目录

#### 修改配置文件

```json
{
    "account_mapping": [
        {
            "username": "user_a",
            "password": "password",
            "permissions": [
                "+"
            ]
        },
        {
            "username": "user_b",
            "password": "password",
            "permissions": []
        }
    ],
    "provider_mapping": [
        {
            "prefix": "/",
            "uri": "file:///data/root"
        },
        {
            "prefix": "/~",
            "uri": "file:///data/homes",
            "home_dir": true
        }
    ]
}
```

#### 创建并启动容器

```
docker run --restart always -p 0.0.0.0:8000:8000 \
  -v /your/data:/data -v /your/data/homes:/data/homes \
  --name asgi-webdav ray1ex/asgi-webdav
```

#### 配置说明

家目录路径对应表

| 用户       | URL      | Docker 容器内路径             | 宿主机器路径                        |
|----------|----------|--------------------------|-------------------------------|
| `user_a` | `/~`     | `/data/homes/user_a`     | `/your/data/homes/user_a`     |
| `user_a` | `/~/sub` | `/data/homes/user_a/sub` | `/your/data/homes/user_a/sub` |
| `user_b` | `/~`     | `/data/homes/user_b`     | `/your/data/homes/user_b`     |
| `user_b` | `/~/sub` | `/data/homes/user_b/sub` | `/your/data/homes/user_b/sub` |

> 如果用户对应的同名子目录不存在，会导致请求家目录时失败。请自行在宿主机上创建 `/your/data/homes/user_a` 等路径
>
> 即便一个用户没有任何共享目录的访问权限，也有权访问自己的所有家目录
>
> 系统允许多个家目录同时存在，比如：`/~` `/home`

## 链接客户端

以下以服务端网址为 `https://your.domain.com` 为例；实际更常见的网址一般为 `https://your.domain.com/my/dav/sub/dir/path`

如果你的 WebDAV 根路径为 `https://domain` 在 WebDAV 根目录下分别有 `/path1` `/path1/sub1` `/path2` 这几个子目录；那么链接的时候分别使用 `https://domain` `https://domain/path1` `https://domain/path1/sub1` `https://domain/path2` 都是可以的

### macOS

在 `访达/Finder` 的菜单 `前往`-`连接服务器...`；然后在弹出窗口中输入 `https://your.domain.com/any/webdav/path`；然后点击 `连接` ；输入用户名/密码即可

### Windows

在 `文件管理器` 左栏 `网络` 处点击鼠标 `右键`；选择 `映射网络驱动器`；在 `文件夹` 栏目输入 `https://your.domain.com`；然后点击 `完成`；输入用户名/密码即可

## 杂技

### Window 资源管理器"映射网络驱动器"

当资源管理器映使用 WebDAV 射网络磁盘的时候，如果服务端提供的是 HTTP 链接而非 HTTPS 链接，同时服务端不主动提供 Digest 认证的情况下会导致映射失败(HTTPS 环境支持 Basic 认证方式)

配置文件修改方法如下:
```json
{
    "http_digest_auth": {
        "enable": false,
        "enable_rule": "Microsoft-WebDAV-MiniRedir|其他客户端UserAgent"
    }
}
```
