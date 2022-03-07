# Changelog

## 1.0.0
- Change docker base image from slim -> alpine, 
- Add non-root support in docker container
- Add new feature: hide file in directory
- Remove feature: DirBrowserIgnore
- Add hashlib support for stored password
- Add LDAP support for stored password 

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
- Add logging page: /_/admin/logging
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
