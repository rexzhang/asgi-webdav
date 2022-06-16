# Cross-Origin Resource Sharing (CORS)

## Enable CORS, allow any Origin

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

## Allow multiple Origin

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

## Based on the regular expressions allowed Origin

```json
{
    "cors": {
        "enable": true,
        "allow_origin_regex": "^https://cors.*"
    }
}
```

## Based on the regular expressions allowed URL

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

## Allowed HTTP methods

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