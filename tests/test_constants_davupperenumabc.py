import json
from enum import auto

import pytest

from asgi_webdav.auth import DAVPasswordType
from asgi_webdav.constants import (
    DAVLowerEnumAbc,
    DAVMethod,
    DAVSenderName,
    DAVUpperEnumAbc,
)


class UpperEnum(DAVUpperEnumAbc):
    ONE = auto()
    Two = auto()
    three = "3rD"


class TestDAVUpperEnumAbc:
    def test_auto_upper_value(self):
        assert UpperEnum.ONE.value == "ONE"
        assert UpperEnum.Two.value == "TWO"
        assert UpperEnum.three.value == "3rD"

        assert str(UpperEnum.ONE) == "ONE"
        assert str(UpperEnum.Two) == "TWO"
        assert str(UpperEnum.three) == "3rD"

    def test_lable(self):
        assert UpperEnum.ONE.label == "ONE"
        assert UpperEnum.Two.label == "TWO"
        assert UpperEnum.three.label == "3rD"

    def test_no_default_value(self):
        with pytest.raises(ValueError):
            UpperEnum("default")

    def test_incorrect_value_type(self):
        with pytest.raises(ValueError):
            UpperEnum(999)

    def test_enum_names_values_and_mapping(self):
        assert UpperEnum.names() == ["ONE", "Two", "three"]
        assert UpperEnum.values() == ["ONE", "TWO", "3rD"]
        assert UpperEnum.value_label_mapping() == {
            "ONE": "ONE",
            "TWO": "TWO",
            "3rD": "3rD",
        }


class LowerEnum(DAVLowerEnumAbc):
    ONE = auto()
    Two = auto()
    three = "3rD"


class TestDAVLowerEnumAbc:
    def test_auto_upper_value(self):
        assert LowerEnum.ONE.value == "one"
        assert LowerEnum.Two.value == "two"
        assert LowerEnum.three.value == "3rD"

        assert str(LowerEnum.ONE) == "one"
        assert str(LowerEnum.Two) == "two"
        assert str(LowerEnum.three) == "3rD"

    def test_lable(self):
        assert LowerEnum.ONE.label == "one"
        assert LowerEnum.Two.label == "two"
        assert LowerEnum.three.label == "3rD"

    def test_no_default_value(self):
        with pytest.raises(ValueError):
            LowerEnum("default")

    def test_incorrect_value_type(self):
        with pytest.raises(ValueError):
            LowerEnum(999)

    def test_enum_names_values_and_mapping(self):
        assert LowerEnum.names() == ["ONE", "Two", "three"]
        assert LowerEnum.values() == ["one", "two", "3rD"]
        assert LowerEnum.value_label_mapping() == {
            "one": "one",
            "two": "two",
            "3rD": "3rD",
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


class TestStrEnumBehavior:
    def test_member_compares_as_str(self):
        assert DAVMethod.GET == "GET"
        assert DAVMethod.GET in {"GET"}
        assert hash(DAVMethod.GET) == hash("GET")

    def test_member_format_and_json(self):
        assert f"{DAVSenderName.ZSTD}" == "zstd"
        assert json.dumps(DAVSenderName.RAW) == '"raw"'

    def test_case_insensitive_lookup(self):
        assert DAVMethod("get") is DAVMethod.GET
