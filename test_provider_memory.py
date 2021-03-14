from asgi_webdav.constants import (
    DAVPath,
)
from asgi_webdav.provider.memory import FileSystemMember


def test_file_system_member():
    root = FileSystemMember(
        name='root',
        basic_property=dict(),
        extra_property=dict(),
        is_file=False
    )

    root.add_file_child('f1', b'')
    root.add_path_child('p1')
    assert root.member_exists(DAVPath('/f1'))
    assert root.member_exists(DAVPath('/p1'))
    assert not root.member_exists(DAVPath('/xxx'))

    root_p1 = root.get_member(DAVPath('/p1'))
    assert not root_p1.member_exists(DAVPath('/f1_1'))
    root_p1.add_file_child('f1_1', b'')
    assert root_p1.member_exists(DAVPath('/f1_1'))
    assert root.member_exists(DAVPath('/p1/f1_1'))
