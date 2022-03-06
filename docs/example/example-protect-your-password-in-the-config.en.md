# Example: Protect your password in the config

```json
{
    "account_mapping": [
        {"username": "user-open", "password": "password", "permissions": ["+"]},
        {
            "username": "user-hashlib",
            "password": "hashlib:sha256:salt:291e247d155354e48fec2b579637782446821935fc96a5a08a0b7885179c408b",
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

## HTTP Digest Mode
TODO

## OpenLDAP Mode
TODO

## Compatibility

|               | HTTP Basic auth | HTTP Digest auth |
|---------------|-----------------|------------------|
| Raw Mode      | Y               | Y                |
| hashlib Mode  | Y               | N                |
| OpenLDAP Mode | Y               | N                |
