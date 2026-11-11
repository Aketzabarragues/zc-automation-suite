"""Constantes XPath para SimaticML (Siemens TIA Scripting).

Centraliza los wildcards XPath que se usan en parser y modifier de
``PlcUserConstant``. Usar ``{*}`` (sintaxis Python 3.8+) evita
hardcodear el namespace concreto del esquema SimaticML (que
cambia entre versiones de TIA Portal).

Atributos:
    USER_CONSTANT_TAG: XPath para nodos ``SW.Tags.PlcUserConstant``.
    NAME_TAG: XPath para el indice ``<Name>`` dentro de AttributeList.
    VALUE_TAG: XPath para el indice ``<Value>`` dentro de AttributeList.
    COMMENT_TAG: XPath para el indice ``<Comment>`` dentro de AttributeList.
    OBJECT_LIST_TAG: XPath para ``<ObjectList>`` (contenedor de
        sub-elementos, p.ej. ``<MultilingualText>`` para comments).
    MULTI_LINGUAL_TEXT_TAG: XPath para ``<MultilingualText>``
        (estructura del comment per-constant en TIA V21).
    TEXT_TAG: XPath para ``<Text>`` dentro de AttributeList del
        ``<MultilingualTextItem>``.
"""
from __future__ import annotations

USER_CONSTANT_TAG: str = "{*}SW.Tags.PlcUserConstant"
NAME_TAG: str = "{*}Name"
VALUE_TAG: str = "{*}Value"
COMMENT_TAG: str = "{*}Comment"
OBJECT_LIST_TAG: str = "{*}ObjectList"
MULTI_LINGUAL_TEXT_TAG: str = "{*}MultilingualText"
TEXT_TAG: str = "{*}Text"


__all__ = [
    "COMMENT_TAG",
    "MULTI_LINGUAL_TEXT_TAG",
    "NAME_TAG",
    "OBJECT_LIST_TAG",
    "TEXT_TAG",
    "USER_CONSTANT_TAG",
    "VALUE_TAG",
]
