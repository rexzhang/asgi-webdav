from asgi_webdav.constants import (
    DAVPath,
)


def test_basic():
    path = DAVPath('/a/b/c')

    assert path.raw == '/a/b/c'
    assert path.parts == ['a', 'b', 'c']
    assert path.count == 3
    assert path.startswith(DAVPath('/a/b'))
    assert path.get_child(DAVPath('/a/b')) == DAVPath('/c')
    assert path.add_child('d') == DAVPath('/a/b/c/d')
