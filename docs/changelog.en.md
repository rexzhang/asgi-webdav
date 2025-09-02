# Changelog

## 1.6.0

- feat: new config, HTTPBasicAuth.cache_timeout
- Optionally expire authentication cache entries after a defined time, thanks [PIC](https://www.pic.es)
- feat: new config, Compression.enable
- feat: both support .toml and .json config file
- feat: support optional anonymous user, thanks [PIC](https://www.pic.es)

## 1.5.0 - 20250628

- Breaking Change
  - feat: `config.Provider` has new `ignore_property_extra` poperty, default is `True`
- Allow authenticating any user from LDAP server, thanks [PIC](https://www.pic.es)
- feat: better timezone support, get timezone from env `TZ`
- feat: `HTTPBasicAuth`'s cache is now configurable

## 1.4.2 - 20250424

- Fix, ensure expected HTTP response header is included in responses, thanks [SilviaSWR](https://github.com/SilviaSWR)
- Add, handle non-existing parent folder, thanks [SilviaSWR](https://github.com/SilviaSWR)

## 1.4.1 - 20240626

- Add, config in-container host,port and configfile by env, thanks [bonjour-py](https://github.com/bonjour-py)
- Add, push docker image to ghcr by github action, thanks [bonjour-py](https://github.com/bonjour-py)

## 1.4.0 - 20240319

- Add a dead simple implementation for "read only" mode, it's not a WebDAV's ACL "read only"
- Add, take query_string from ASGI scope to DAVRequest
- Add, DAVRequest support all HTTP method, include POST and UNKNOWN
- Add, new config for logging
- Update, optimization `HideFileInDir` logic
- Update client user-agent regex
- Upgrade xmltodict to 0.13.x
- Update pydantic to 2.4+
- Update docs

## 1.3.2 - 2022-10-08

- Fix method PROPFIND's compatibility(litmus/0.13 neon/0.31.2)

## 1.3.1 - 2022-09-30

- Add ARMv7 into Docker targets

## 1.3.0 - 2022-09-30

- Add `examples.work_together_with_other_asgi_app.py`, thanks [davidbrochart](https://github.com/davidbrochart)
- LDAP is now optional
- uvicorn is now optional
- `FileSystemProvider` uses more aiofiles API
- Change `DAVRequest.depth`'s default value from `DAVDepth.infinity` to DAVDepth.d0
- ~~PROPFIND will return 200 if only one DAV property response in the return~~

## 1.2.0 - 2022-06-20

- Broken change
  - Change `Config.compression.user_content_type_rule` to `Config.compression.content_type_user_rule`
- Add more support for HTTP header: Range
- Fix HTTP Digest rules checker
- Add a new property `DAVResponse.compression_method`

## 1.1.0 - 2022-06-05

- Add new feature: CORS
- Reduce Docker image size

## 1.0.0 - 2022-03-09

- Broken change
  - Remove feature: DirBrowserIgnore
- Change docker base image from slim -> alpine,
- Add non-root support in docker container
- Add new feature: hide file in directory
- Add hashlib mode for stored password
- Add HTTP Digest mode for stored password
- Add LDAP mode for stored password

## 0.9.1 - 2021-08-02

- Fix bug

## 0.9.0 - 2021-08-02

- Add Config.http_digest_auth.enable_rule

## 0.8.1 - 2021-07-30

- Fix Dockerfile

## 0.8.0 - 2021-07-30

- Real client ip address
- CLI support
- Release Windows/macOS package

## 0.7.0 - 2021-07-03

- Add logging page: /\_/admin/logging
- Disable Digest auth in default
- Support header Accept-Ranges/Range/Content-Range (Incomplete implementation)
- Fix bug: can't access home dir when it can't access share dir

## 0.6.1 - 2021-06-23

- Compatible with Window10 Explorer(Microsoft-WebDAV-MiniRedir/10.0.19043)

## 0.6.0 - 2021-06-22

- Support HTTP Digest authentication
- Code optimization

## 0.5.0 - 2021-05-14

- Text file charset detect
- Support gzip/brotli in response
- Fix bug: Content-Encoding

## 0.4.0 - 2021-05-10

- Support ignore rules in web dir browser
- Configurable guess_type()

## 0.3.1 - 2021-05-06

- Broken change:
  - Config.username/password => Config.account_mapping
  - Environment Variable Name
- Add multi-account support
- Add permission support
- Add home_dir support

## 0.2.1 - 2021-04-27

- Add web dir browser

## 0.1.1 - 2021-03-26

- Fix bug

## 0.1.0 - 2021-03-25

- first release
