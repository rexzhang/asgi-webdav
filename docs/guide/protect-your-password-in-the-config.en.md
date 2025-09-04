# Protect your password in the configuration file

```json
{
  "account_mapping": [
    { "username": "user-raw", "password": "password", "permissions": ["+"] },
    {
      "username": "user-hashlib",
      "password": "<hashlib>:sha256:salt:291e247d155354e48fec2b579637782446821935fc96a5a08a0b7885179c408b",
      "permissions": ["+^/$"]
    },
    {
      "username": "user-digest",
      "password": "<digest>:ASGI-WebDAV:c1d34f1e0f457c4de05b7468d5165567",
      "permissions": ["+^/$"]
    },
    {
      "username": "user-ldap",
      "password": "<ldap>#1#ldaps://your.ldap.server.com#SIMPLE#uid=user-ldap,cn=users,dc=your.ldap.server.com",
      "permissions": ["+^/$"]
    },
    {
      "username": "*ldap",
      "password": "<ldap>#2#ldaps://your.ldap.server.com#cert_policy=try#uid={username},cn=users,dc=your.ldap.server.com",
      "permissions": ["+^/$"]
    }
  ]
}
```

## Raw Mode

user `user-raw`'s password is real password

## hashlib Mode

`password`'s format is `"<hashlib>:{algorithm}:{salt}:{hashed-password}"`

### {algorithm}

A list of supported `{algorithms}` can be found at [Python's docs](https://docs.python.org/3.10/library/hashlib.html)

The commonly used algorithms:

- sha256
- sha384
- sha512
- blake2b (optimized for 64-bit platforms)
- blake2s (optimized for 8- to 32-bit platforms)

### {salt}

`{salt}` can be any string

### {hashed-password}

`{hashed-password}`'s format is `ALGORITHM(bytes("{salt}:{password}")).hexdigest()`

example:

- {algorithm}: sha256
- {salt}: `salt`
- {password}: `password`

```text
>>> import hashlib
>>> hashlib.new("sha256", "{}:{}".format("salt", "password").encode("utf-8")).hexdigest()
'291e247d155354e48fec2b579637782446821935fc96a5a08a0b7885179c408b'
```

### Ref

- <https://en.wikipedia.org/wiki/Comparison_of_cryptographic_hash_functions>

## HTTP Digest Mode

`password`'s format is `<digest>:{realm}:{HA1}`

### {realm}

`ASGI-WebDAV`

### {HA1}

`{HA1}`'s format is `md5(bytes("{username}:{realm}:{password}")).hexdigest()`

example:

- {username}: `user-digest`
- {realm}: `ASGI-WebDAV`
- {password}: `password`

```text
>>> import hashlib
>>> hashlib.new("md5", "{}:{}:{}".format("user-digest", "ASGI-WebDAV", "password").encode("utf-8")).hexdigest()
'c1d34f1e0f457c4de05b7468d5165567'
```

### Ref

- [RFC2617](https://datatracker.ietf.org/doc/html/rfc2617)

## LDAP(v1) (experimental)

### password format

```text
"<ldap>#1#{ldap-uri}#{mechanism}#{ldap-user}"
```

### {ldap-uri}

Example:

`ldap://your.ldap.server.com` `ldaps://your.tls.ldap.server.com`

- [Official Website](https://ldap.com/ldap-urls/)
- [RFC4516](https://docs.ldap.com/specs/rfc4516.txt)

### {mechanism}

Example:

`SIMPLE` ...

### {ldap-user}

Example:

`uid=you-name,cn=users,dc=ldap,dc=server,dc=com`

## LDAP(v2)

### username

Use `"*ldap"` as `username`

### password format

```text
"<ldap>#2#ldaps://{ldap-uri}#{params}#{user-dn-pattern}"
```

### permissions

!!! WARNING

    `permissions` will be automatically applied to all ldap accounts.

### {ldap-uri}

Example:

`ldap://your.ldap.server.com` `ldaps://your.tls.ldap.server.com`

#### Ref

- [Official Website](https://ldap.com/ldap-urls/)
- [RFC4516](https://docs.ldap.com/specs/rfc4516.txt)

### {params}

This is a query string specifying additional optional settings. Only one is supported as of now:

`cert_policy` indicates the policy about server verification. The allowed values are:

- `try` or `demand`: The server cert will be verified, and if it fais, an error will be raised. This is the default.
- `never` or `allow`: The server cert will be used without any verification.

Example:

`cert_policy=try`

#### Ref

- [RFC1866](https://datatracker.ietf.org/doc/html/rfc1866)

### {user-dn-pattern}

Specify the user DN pattern, with a `username` substitution field. Example:

`uid={username},cn=users,dc=ldap,dc=server,dc=com`

## Compatibility

|                  | HTTP Basic auth | HTTP Digest auth |
| ---------------- | --------------- | ---------------- |
| Raw Mode         | Y               | Y                |
| hashlib Mode     | Y               | N                |
| HTTP Digest Mode | Y               | Y                |
| LDAP(v1)         | Y               | N                |
| LDAP(v2)         | Y               | N                |
