# Protect your password in the configuration file

```json
{
    "account_mapping": [
        {"username": "user-open", "password": "password", "permissions": ["+"]},
        {
            "username": "user-hashlib",
            "password": "hashlib:sha256:salt:291e247d155354e48fec2b579637782446821935fc96a5a08a0b7885179c408b",
            "permissions": ["+^/$"]
        },
        {
            "username": "user-ldap",
            "password": "ldap#1#ldaps://your.ldap.server.com#SIMPLE#uid=user-ldap,cn=users,dc=your.ldap.server.com",
            "permissions": ["+^/$"]
        }
    ]
}
```

## Raw Mode

user `user-open`'s password is real password

## hashlib Mode

`password`'s format is `"hashlib:{algorithm}:{salt}:{hashed-password}"`

### algorithm
A list of supported `algorithms` can be found at [Python's docs](https://docs.python.org/3.10/library/hashlib.html)

The commonly used algorithms:

- sha256
- sha384
- sha512
- blake2b (optimized for 64-bit platforms)
- blake2s (optimized for 8- to 32-bit platforms)

### salt
`salt` can be any string

### hashed-password
example:

- algorithm: sha256
- salt: `salt`
- password: `password`

```
>>> import hashlib
>>> hashlib.new("sha256", "{}:{}".format("salt", "password").encode("utf-8")).hexdigest()
'291e247d155354e48fec2b579637782446821935fc96a5a08a0b7885179c408b'
```

### Ref

- https://en.wikipedia.org/wiki/Comparison_of_cryptographic_hash_functions

## LDAP Mode (experimental)
`password`'s format is `"ldap#1#{ldap-uri}#{mechanism}#{ldap-user}"`

### ldap-uri

Example:

`ldap://your.ldap.server.com` `ldaps://your.tls.ldap.server.com`

#### Ref

- [Official Website](https://ldap.com/ldap-urls/)
- [RFC4516](https://docs.ldap.com/specs/rfc4516.txt)

### mechanism

Example:

`SIMPLE` ...

### ldap-user

Example:

`uid=you-name,cn=users,dc=ldap,dc=server,dc=com`

## HTTP Digest Mode
TODO


## Compatibility

|              | HTTP Basic auth | HTTP Digest auth |
|--------------|-----------------|------------------|
| Raw Mode     | Y               | Y                |
| hashlib Mode | Y               | N                |
| LDAP Mode    | Y               | N                |
