# Compatibility

## Compatible Clients

| Client                                                   | First tested version | Remarks                                                  |
|----------------------------------------------------------|----------------------|----------------------------------------------------------|
| Firefox/Chrome/Safari                                    | 0.1.0                | -                                                        |
| macOS finder(WebDAVFS/3.0.0)                             | 0.1.0                | -                                                        |
| Window10 Explorer(Microsoft-WebDAV-MiniRedir/10.0.19043) | 0.6.1                | Basic auth only support HTTPS, HTTP please enable Digest |
| Joplin(Joplin/1.0)                                       | 0.1.0                | -                                                        |
| OmniFocus(OmniFocus-Mac/149.14.0/v3.11.7)                | 0.1.0                | -                                                        |
| WinSCP(WinSCP/5.19.1 neon/0.31.2)                        | 0.7.0                | Only support Basic auth                                  |

## Compatibility Test Results

Test in [litmus(0.13)](http://www.webdav.org/neon/litmus)

```shell
python3 -m asgi_webdav --litmus
```

```shell
litmus http://192.168.200.198:8000/provider/fs username password
# or
litmus http://192.168.200.198:8000/provider/memory username password
```

```text
Version string: neon 0.30.2: Library build, IPv6, libxml 2.9.4, zlib 1.2.11, GNU TLS 3.6.6.
```

### ASGI WebDAV

- Version: 0.3.1

```text
-> running `basic':
 0. init.................. pass
 1. begin................. pass
 2. options............... pass
 3. put_get............... pass
 4. put_get_utf8_segment.. pass
 5. put_no_parent......... pass
 6. mkcol_over_plain...... pass
 7. delete................ pass
 8. delete_null........... pass
 9. delete_fragment....... pass
10. mkcol................. pass
11. mkcol_again........... pass
12. delete_coll........... pass
13. mkcol_no_parent....... pass
14. mkcol_with_body....... pass
15. finish................ pass
<- summary for `basic': of 16 tests run: 16 passed, 0 failed. 100.0%
-> running `copymove':
 0. init.................. pass
 1. begin................. pass
 2. copy_init............. pass
 3. copy_simple........... pass
 4. copy_overwrite........ pass
 5. copy_nodestcoll....... pass
 6. copy_cleanup.......... pass
 7. copy_coll............. pass
 8. copy_shallow.......... pass
 9. move.................. pass
10. move_coll............. pass
11. move_cleanup.......... pass
12. finish................ pass
<- summary for `copymove': of 13 tests run: 13 passed, 0 failed. 100.0%
-> running `props':
 0. init.................. pass
 1. begin................. pass
 2. propfind_invalid...... pass
 3. propfind_invalid2..... pass
 4. propfind_d0........... pass
 5. propinit.............. pass
 6. propset............... pass
 7. propget............... pass
 8. propextended.......... pass
 9. propmove.............. pass
10. propget............... pass
11. propdeletes........... pass
12. propget............... pass
13. propreplace........... pass
14. propget............... pass
15. propnullns............ pass
16. propget............... pass
17. prophighunicode....... pass
18. propget............... pass
19. propremoveset......... pass
20. propget............... pass
21. propsetremove......... pass
22. propget............... pass
23. propvalnspace......... pass
24. propwformed........... pass
25. propinit.............. pass
26. propmanyns............ pass
27. propget............... pass
28. propcleanup........... pass
29. finish................ pass
<- summary for `props': of 30 tests run: 30 passed, 0 failed. 100.0%
-> running `locks':
 0. init.................. pass
 1. begin................. pass
 2. options............... pass
 3. precond............... pass
 4. init_locks............ pass
 5. put................... pass
 6. lock_excl............. pass
 7. discover.............. pass
 8. refresh............... pass
 9. notowner_modify....... pass
10. notowner_lock......... pass
11. owner_modify.......... pass
12. notowner_modify....... pass
13. notowner_lock......... pass
14. copy.................. pass
15. cond_put.............. pass
16. fail_cond_put......... pass
17. cond_put_with_not..... pass
18. cond_put_corrupt_token WARNING: PUT failed with 412 not 423
    ...................... pass (with 1 warning)
19. complex_cond_put...... pass
20. fail_complex_cond_put. pass
21. unlock................ pass
22. fail_cond_put_unlocked pass
23. lock_shared........... pass
24. notowner_modify....... pass
25. notowner_lock......... pass
26. owner_modify.......... pass
27. double_sharedlock..... pass
28. notowner_modify....... pass
29. notowner_lock......... pass
30. unlock................ pass
31. prep_collection....... pass
32. lock_collection....... pass
33. owner_modify.......... pass
34. notowner_modify....... pass
35. refresh............... pass
36. indirect_refresh...... pass
37. unlock................ pass
38. unmapped_lock......... WARNING: LOCK on unmapped url returned 200 not 201 (RFC4918:S7.3)
    ...................... pass (with 1 warning)
39. unlock................ pass
40. finish................ pass
<- summary for `locks': of 41 tests run: 41 passed, 0 failed. 100.0%
-> 2 warnings were issued.
-> running `http':
 0. init.................. pass
 1. begin................. pass
 2. expect100............. pass
 3. finish................ pass
<- summary for `http': of 4 tests run: 4 passed, 0 failed. 100.0%
```

### Apache mod_webdav in Docker

- From: [bytemark/webdav]((https://hub.docker.com/r/bytemark/webdav))
- Version: 2.4
- Digest: c124350447bb
- Build Time: 2018-12-14

```shell
docker pull bytemark/webdav
docker run --restart always \
  -e AUTH_TYPE=Digest -e USERNAME=username -e PASSWORD=password \
  --publish 8000:80 -d bytemark/webdav
```

```text
-> running `basic':
 0. init.................. pass
 1. begin................. pass
 2. options............... pass
 3. put_get............... pass
 4. put_get_utf8_segment.. pass
 5. put_no_parent......... pass
 6. mkcol_over_plain...... pass
 7. delete................ pass
 8. delete_null........... pass
 9. delete_fragment....... pass
10. mkcol................. pass
11. mkcol_again........... pass
12. delete_coll........... pass
13. mkcol_no_parent....... pass
14. mkcol_with_body....... pass
15. finish................ pass
<- summary for `basic': of 16 tests run: 16 passed, 0 failed. 100.0%
-> running `copymove':
 0. init.................. pass
 1. begin................. pass
 2. copy_init............. pass
 3. copy_simple........... pass
 4. copy_overwrite........ pass
 5. copy_nodestcoll....... pass
 6. copy_cleanup.......... pass
 7. copy_coll............. pass
 8. copy_shallow.......... pass
 9. move.................. pass
10. move_coll............. pass
11. move_cleanup.......... pass
12. finish................ pass
<- summary for `copymove': of 13 tests run: 13 passed, 0 failed. 100.0%
-> running `props':
 0. init.................. pass
 1. begin................. pass
 2. propfind_invalid...... pass
 3. propfind_invalid2..... pass
 4. propfind_d0........... pass
 5. propinit.............. pass
 6. propset............... pass
 7. propget............... pass
 8. propextended.......... pass
 9. propmove.............. pass
10. propget............... pass
11. propdeletes........... pass
12. propget............... pass
13. propreplace........... pass
14. propget............... pass
15. propnullns............ pass
16. propget............... pass
17. prophighunicode....... pass
18. propget............... pass
19. propremoveset......... pass
20. propget............... pass
21. propsetremove......... pass
22. propget............... pass
23. propvalnspace......... pass
24. propwformed........... pass
25. propinit.............. pass
26. propmanyns............ pass
27. propget............... pass
28. propcleanup........... pass
29. finish................ pass
<- summary for `props': of 30 tests run: 30 passed, 0 failed. 100.0%
-> running `locks':
 0. init.................. pass
 1. begin................. pass
 2. options............... pass
 3. precond............... pass
 4. init_locks............ pass
 5. put................... pass
 6. lock_excl............. pass
 7. discover.............. pass
 8. refresh............... pass
 9. notowner_modify....... pass
10. notowner_lock......... pass
11. owner_modify.......... pass
12. notowner_modify....... pass
13. notowner_lock......... pass
14. copy.................. pass
15. cond_put.............. pass
16. fail_cond_put......... pass
17. cond_put_with_not..... pass
18. cond_put_corrupt_token WARNING: PUT failed with 400 not 423
    ...................... pass (with 1 warning)
19. complex_cond_put...... pass
20. fail_complex_cond_put. pass
21. unlock................ pass
22. fail_cond_put_unlocked pass
23. lock_shared........... pass
24. notowner_modify....... pass
25. notowner_lock......... pass
26. owner_modify.......... pass
27. double_sharedlock..... pass
28. notowner_modify....... pass
29. notowner_lock......... pass
30. unlock................ pass
31. prep_collection....... pass
32. lock_collection....... pass
33. owner_modify.......... pass
34. notowner_modify....... pass
35. refresh............... pass
36. indirect_refresh...... pass
37. unlock................ pass
38. unmapped_lock......... WARNING: LOCK on unmapped url returned 200 not 201 (RFC4918:S7.3)
    ...................... pass (with 1 warning)
39. unlock................ pass
40. finish................ pass
<- summary for `locks': of 41 tests run: 41 passed, 0 failed. 100.0%
-> 2 warnings were issued.
-> running `http':
 0. init.................. pass
 1. begin................. pass
 2. expect100............. pass
 3. finish................ pass
<- summary for `http': of 4 tests run: 4 passed, 0 failed. 100.0%
```

### Nginx in Docker

- From: [ugeek/webdav](https://hub.docker.com/r/ugeek/webdav)
- Digest: b5e54f00265e
- Build Time: 2021-02-09

```shell
docker pull ugeek/webdav:latest
docker run --name webdav \
  --restart=unless-stopped \
  -p 8000:80 \
  -e USERNAME=username \
  -e PASSWORD=password \
  -e TZ=Europe/Madrid  \
  -e UDI=1000 \
  -e GID=1000 \
  -d  ugeek/webdav:amd64
```

```text
-> running `basic':
 0. init.................. pass
 1. begin................. pass
 2. options............... WARNING: server does not claim Class 2 compliance
    ...................... pass (with 1 warning)
 3. put_get............... pass
 4. put_get_utf8_segment.. pass
 5. put_no_parent......... pass
 6. mkcol_over_plain...... pass
 7. delete................ pass
 8. delete_null........... pass
 9. delete_fragment....... WARNING: DELETE removed collection resource with Request-URI including fragment; unsafe
    ...................... pass (with 1 warning)
10. mkcol................. pass
11. mkcol_again........... pass
12. delete_coll........... pass
13. mkcol_no_parent....... pass
14. mkcol_with_body....... pass
15. finish................ pass
<- summary for `basic': of 16 tests run: 16 passed, 0 failed. 100.0%
-> 2 warnings were issued.
-> running `copymove':
 0. init.................. pass
 1. begin................. pass
 2. copy_init............. pass
 3. copy_simple........... WARNING: COPY to new resource should give 201 (RFC2518:S8.8.5)
    ...................... pass (with 1 warning)
 4. copy_overwrite........ FAIL (COPY overwrites collection: 409 Conflict)
 5. copy_nodestcoll....... WARNING: COPY to non-existant collection '/litmus/nonesuch' gave '500 Internal Server Error' not 409 (RFC2518:S8.8.5)
    ...................... pass (with 1 warning)
 6. copy_cleanup.......... pass
 7. copy_coll............. pass
 8. copy_shallow.......... pass
 9. move.................. WARNING: MOVE to new resource didn't give 201
    ...................... FAIL (MOVE overwrites collection `/litmus/movecoll/' to `/litmus/movedest': 409 Conflict)
10. move_coll............. FAIL (MOVE collection `/litmus/mvdest2/' over non-collection `/litmus/mvnoncoll' with overwrite: 409 Conflict)
11. move_cleanup.......... pass
12. finish................ pass
<- summary for `copymove': of 13 tests run: 10 passed, 3 failed. 76.9%
-> 3 warnings were issued.
See debug.log for network/debug traces.
```

### Summary

|                             | basic      | copymove   | props | locks      | http |
|-----------------------------|------------|------------|-------|------------|------|
| ASGI WebDAV                 | pass       | pass       | pass  | 2 warnings | pass |
| Apache mod_webdav in docker | pass       | pass       | pass  | 2 warnings | pass |
| Nginx in Docker             | 2 warnings | 3 warnings | skip  | skip       | skip |
