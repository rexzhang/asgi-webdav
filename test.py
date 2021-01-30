from webdav3.client import Client

options = {
    'webdav_hostname': "http://127.0.0.1:8000",
    'webdav_login': "admin",
    'webdav_password': "password",
    'webdav_verbose': True
}
client = Client(options)

# assert client.check('')
# assert client.check('/')
# assert client.check('joplin_ext/')
# assert client.check('joplin_ext')
#
# assert client.check('dir1')
# assert client.check('dir1/file1')
# assert client.check('dir1/file1/')
# assert not client.check('dir2')

client.clean('litmus')

# print(client.info("dir1/file1"))
# print(client.info("dir1/"))
#
# free_size = client.free()
#
# files1 = client.list()
# files2 = client.list("dir1")
#
# client.mkdir("dir1/dir2")
# client.clean("dir1/dir2")
