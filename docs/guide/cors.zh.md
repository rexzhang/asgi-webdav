# 跨源资源共享 (CORS)

## 打开 CORS 支持, 并允许任意 Origin

```json
{
    "cors": {
        "enable": true,
        "allow_origins": [
            "*"
        ]
    }
}
```

## 允许多个 Origin

```json
{
    "cors": {
        "enable": true,
        "allow_origins": [
            "https://i.am.origin.com",
            "https://me.too.com"
        ]
    }
}
```

## 基于正则表达式允许的 Origin

```json
{
    "cors": {
        "enable": true,
        "allow_origin_regex": "^https://cors.*"
    }
}
```

## 基于正则表达式允许的 URL 范围

```json
{
    "cors": {
        "enable": true,
        "allow_url_regex": "^/cors/path.*",
        "allow_origins": [
            "*"
        ]
    }
}
```

## 允许的 HTTP 方法

```json
{
    "cors": {
        "enable": true,
        "allow_origins": [
            "*"
        ],
        "allow_methods": [
            "GET",
            "HEAD",
            "POST"
        ]
    }
}
```