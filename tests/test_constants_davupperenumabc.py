from enum import auto

import pytest

from asgi_webdav.auth import DAVPasswordType
from asgi_webdav.constants import DAVLowerEnumAbc, DAVMethod, DAVUpperEnumAbc


class UpperEnum(DAVUpperEnumAbc):
    ONE = auto()
    Two = auto()
    three = "3rD"


class TestDAVUpperEnumAbc:
    def test_auto_upper_value(self):
        assert UpperEnum.ONE.value == "ONE"
        assert UpperEnum.Two.value == "TWO"
        assert UpperEnum.three.value == "THREE"

        assert str(UpperEnum.ONE) == "UpperEnum.ONE"
        assert str(UpperEnum.Two) == "UpperEnum.Two"
        assert str(UpperEnum.three) == "UpperEnum.three"

    def test_lable(self):
        assert UpperEnum.ONE.label == "1"
        assert UpperEnum.Two.label == "2"
        assert UpperEnum.three.label == "3rD"

    def test_no_default_value(self):
        with pytest.raises(ValueError):
            UpperEnum("default")

    def test_incorrect_value_type(self):
        with pytest.raises(ValueError):
            UpperEnum(999)

    def test_enum_names_values_and_mapping(self):
        assert UpperEnum.names() == ["ONE", "Two", "three"]
        assert UpperEnum.values() == ["ONE", "TWO", "THREE"]
        assert UpperEnum.value_label_mapping() == {
            "ONE": "1",
            "TWO": "2",
            "THREE": "3rD",
        }


class LowerEnum(DAVLowerEnumAbc):
    ONE = auto()
    Two = auto()
    three = "3rD"


class TestDAVLowerEnumAbc:
    def test_auto_upper_value(self):
        assert LowerEnum.ONE.value == "one"
        assert LowerEnum.Two.value == "two"
        assert LowerEnum.three.value == "three"

        assert str(LowerEnum.ONE) == "LowerEnum.ONE"
        assert str(LowerEnum.Two) == "LowerEnum.Two"
        assert str(LowerEnum.three) == "LowerEnum.three"

    def test_lable(self):
        assert LowerEnum.ONE.label == "1"
        assert LowerEnum.Two.label == "2"
        assert LowerEnum.three.label == "3rD"

    def test_no_default_value(self):
        with pytest.raises(ValueError):
            LowerEnum("default")

    def test_incorrect_value_type(self):
        with pytest.raises(ValueError):
            LowerEnum(999)

    def test_enum_names_values_and_mapping(self):
        assert LowerEnum.names() == ["ONE", "Two", "three"]
        assert LowerEnum.values() == ["one", "two", "three"]
        assert LowerEnum.value_label_mapping() == {
            "one": "1",
            "two": "2",
            "three": "3rD",
        }


class UpperEnumDefaultValue(DAVUpperEnumAbc):
    ONE = auto()
    Two = auto()

    @classmethod
    def default_value(cls, value) -> str:
        return "ONE"


class TestDavUpperEnumAbcDefaultValue:
    def test(self):
        assert UpperEnumDefaultValue("default") == UpperEnumDefaultValue.ONE


class TestDAVMethod:
    def test_default_value(self):
        assert DAVMethod("default") == DAVMethod.UNKNOWN


class TestDAVPasswordType:
    def test_default_value(self):
        assert DAVPasswordType("default") == DAVPasswordType.INVALID

    def test_split_value(self):
        assert DAVPasswordType.RAW.split_char == ":"
        assert DAVPasswordType.RAW.split_count == 0

        assert DAVPasswordType.LDAP.split_char == "#"
        assert DAVPasswordType.LDAP.split_count == 5
