"""Modificadores XML para PlcTagTable (SimaticML).

Clases que clonan nodos ``<SW.Tags.PlcTag>`` de una plantilla, actualizan
las etiquetas de nombre/direccion iterando sobre los dispositivos
y guardan el resultado para importacion posterior via
``import_plc_tags_xml``.

Restriccion arquitectonica: este modulo es OFFLINE; no importa
``siemens_tia_scripting``. Usa exclusivamente ``xml.etree.ElementTree``.

Refactor obligatorio: las busquedas XPath NO usan diccionarios de
namespaces hardcoded; se apoyan en la sintaxis de comodin ``{*}``
introducida en Python 3.8 para ser inmunes a cambios de version del
esquema SimaticML de Siemens.

Convencion de mapeo UID (via IT):
    TIA Portal PlcTag no tiene campo nativo "UID". El motor diff IT/OT
    almacena el ``uid`` del Excel en el atributo ``Comment`` del
    PlcTag, mientras que ``Name`` corresponde a ``plc_tag``.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

from areas.alimentacion.domain.models.dispositivos import Dispositivo


# Wildcards XPath. ``{*}`` = cualquier namespace; evita acoplarse a la
# version concreta del esquema (p. ej. ``http://www.siemens.com/...``).
_PLC_TAG = "{*}SW.Tags.PlcTag"
_PLC_USER_CONSTANT = "{*}SW.Tags.PlcUserConstant"
_NAME_TAG = "{*}Name"
_COMMENT_TAG = "{*}Comment"
_VALUE_TAG = "{*}Value"
# Etiquetas de direccion/defensa: probamos varias conocidas para
# cubrir distintas versiones del esquema.
_ADDRESS_TAGS: tuple[str, ...] = (
    "{*}Address",
    "{*}LogicalAddress",
    "{*}MemoryArea",
)


def _get_text(elem: ET.Element | None) -> str:
    """Devuelve ``elem.text`` stripped o ``""`` si elem es None / sin texto."""
    if elem is None:
        return ""
    return (elem.text or "").strip()


class XMLModifier:
    """Clase base: carga un XML SimaticML y permite guardarlo."""

    def __init__(self, xml_path: str | Path) -> None:
        self._path = Path(xml_path)
        if not self._path.is_file():
            raise FileNotFoundError(
                f"No se encontro el archivo XML: '{self._path}'"
            )
        # ``ET.parse`` esta tipado como ``ElementTree[Element | None]`` por
        # invariancia de generics; en la practica nunca devuelve None con
        # un archivo XML valido. Usamos Any para silenciar el warning sin
        # perder el tipado fuerte del ``_root``.
        self._tree: Any = ET.parse(str(self._path))
        self._root: ET.Element = cast(ET.Element, self._tree.getroot())
        self._modified: bool = False

    def save(self, output_path: str | Path) -> None:
        """Escribe el arbol XML modificado en ``output_path``."""
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        self._tree.write(
            str(out), encoding="utf-8", xml_declaration=True
        )

    def was_modified(self) -> bool:
        """Devuelve ``True`` si add/remove mutaron el DOM."""
        return self._modified


class TagTableModifier(XMLModifier):
    """Modifica una PlcTagTable XML clonando nodos ``<{*}SW.Tags.PlcTag>``.

    La inyeccion es **idempotente**: si un PlcTag con el mismo nombre
    (``{*}Name``) ya existe, no se vuelve a insertar.

    Convenciones:
      - ``Name`` <-- ``dispositivo.plc_tag``
      - ``Comment`` <-- ``dispositivo.uid`` (mapeo IT para diff)
    """

    def add_tags(self, dispositivos: list[Dispositivo]) -> int:
        """Anade PlcTag instances desde una lista de objetos del dominio.

        Cada DTO debe implementar el Protocol ``Dispositivo``
        (atributos ``plc_tag`` y ``uid``).

        Returns:
            Numero de PlcTag realmente anadidos (idempotente).
        """
        template = self._find_template_tag()
        if template is None:
            return 0

        existing_names = self._existing_names()
        added = 0
        for dispositivo in dispositivos:
            name = str(getattr(dispositivo, "plc_tag", "")).strip()
            if not name or name in existing_names:
                continue
            uid = str(getattr(dispositivo, "uid", "")).strip()
            address = str(getattr(dispositivo, "descripcion", "")).strip()
            new_tag = deepcopy(template)
            self._update_tag_fields(new_tag, name=name, comment=uid, address=address)
            self._append_after_last_tag(new_tag)
            existing_names.add(name)
            added += 1
        if added > 0:
            self._modified = True
        return added

    def add_tags_by_table(
        self,
        table_name: str,
        dispositivos: list[dict[str, str]],
    ) -> int:
        """Anade PlcTags a la tabla cuyo stem XML coincide con ``table_name``.

        Cada dict debe contener al menos ``plc_tag`` y ``uid``. Es un
        atajo para el motor diff que trabaja con ``{uid: plc_tag}``.
        """
        if self._path.stem != table_name:
            return 0
        template = self._find_template_tag()
        if template is None:
            return 0
        existing_names = self._existing_names()
        added = 0
        for dto in dispositivos:
            name = dto.get("plc_tag", "").strip()
            if not name or name in existing_names:
                continue
            uid = dto.get("uid", "").strip()
            new_tag = deepcopy(template)
            self._update_tag_fields(new_tag, name=name, comment=uid, address="")
            self._append_after_last_tag(new_tag)
            existing_names.add(name)
            added += 1
        if added > 0:
            self._modified = True
        return added

    # Eliminacion por uid (motor diff hibrido)
    def remove_tags(self, uids_to_remove: set[str]) -> int:
        """Elimina PlcTag cuyo ``Comment`` contiene un uid del set.

        TIA Portal PlcTag no tiene campo nativo UID. Por convencion IT
        (ver docstring del modulo), el ``uid`` se almacena en el atributo
        ``Comment``. Si un PlcTag tiene un uid que matchea cualquiera de
        ``uids_to_remove``, se elimina del arbol DOM.

        Returns:
            Numero de PlcTag eliminados (idempotente).
        """
        if not uids_to_remove:
            return 0
        removed = 0
        # ``ET.iter(tag)`` NO soporta wildcard ``{*}``; usamos ``findall``.
        # Hacemos list() porque vamos a mutar el arbol dentro del loop.
        for tag in list(self._root.findall(f".//{_PLC_TAG}")):
            comment = _get_text(tag.find(_COMMENT_TAG))
            if not comment:
                continue
            # El uid puede estar embebido en un Comment mas largo.
            # Usamos match por igualdad exacta primero (caso comun).
            if comment in uids_to_remove:
                parent = self._find_parent_of(tag)
                if parent is not None:
                    parent.remove(tag)
                    removed += 1
        if removed > 0:
            self._modified = True
        return removed

    def read_tags_with_uids(self) -> list[dict[str, str]]:
        """Itera los PlcTags del XML y emite ``[{name, comment, uid}]``.

        ``uid`` se extrae del campo ``Comment`` (convencion IT).
        ``name`` corresponde a ``Name`` (= ``plc_tag`` en TIA).

        Returns:
            Lista de dicts ``{name, comment, uid}`` (uno por PlcTag).
        """
        out: list[dict[str, str]] = []
        # ``ET.iter(tag)`` NO soporta wildcard ``{*}``; usamos ``findall``.
        for tag in self._root.findall(f".//{_PLC_TAG}"):
            name = _get_text(tag.find(_NAME_TAG))
            comment = _get_text(tag.find(_COMMENT_TAG))
            out.append(
                {
                    "name": name,
                    "comment": comment,
                    "uid": comment,
                }
            )
        return out

    def read_user_constants_with_uids(self) -> dict[str, str]:
        """Itera PlcUserConstant del XML y devuelve ``{value_str: plc_tag}``.

        Diferencia clave con ``read_tags_with_uids``:
          - PlcUserConstant tiene ``<Value>`` (slot numǸrico) y ``<Name>`` (plc_tag).
          - PlcTag tiene ``<Name>`` y ``<Comment>`` (uid textual).

        PlcUserConstant es el tipo que almacena N_MAX y los dispositivos
        PlcTag son las variables de instancia. Para el diff de constantes
        usamos el ``<Value>`` (que coincide con ``numero`` del Excel).

        Returns:
            ``dict[str, str]`` con pares ``{value_str: plc_tag}`` (uno por
            PlcUserConstant). Solo incluye constantes casteables a int.
        """
        result: dict[str, str] = {}
        _USER_CONST_TAG = "{*}SW.Tags.PlcUserConstant"
        for const in self._root.findall(f".//{_USER_CONST_TAG}"):
            # FIX: usar ``.//`` (recursivo) porque <Name> y <Value> estǭn
            # dentro de <AttributeList>, no como hijos directos.
            name_el = const.find(f".//{_NAME_TAG}")
            value_el = const.find(f".//{{*}}Value")
            if name_el is None or value_el is None:
                continue
            name = (name_el.text or "").strip()
            value = (value_el.text or "").strip()
            if not name or not value:
                continue
            try:
                int(value)
            except ValueError:
                continue
            result[value] = name
        return result
    def _existing_names(self) -> set[str]:
        """Devuelve el conjunto de nombres ``{*}Name`` ya presentes."""
        result: set[str] = set()
        for tag in self._root.findall(f".//{_PLC_TAG}"):
            txt = _get_text(tag.find(_NAME_TAG))
            if txt:
                result.add(txt)
        return result

    def _find_template_tag(self) -> ET.Element | None:
        """Devuelve el primer nodo ``{*}SW.Tags.PlcTag`` como plantilla."""
        tags = self._root.findall(f".//{_PLC_TAG}")
        return tags[0] if tags else None

    @staticmethod
    def _update_tag_fields(
        tag: ET.Element,
        name: str,
        comment: str,
        address: str,
    ) -> None:
        """Actualiza ``{*}Name``, ``{*}Comment`` y un tag de direccion."""
        name_el = tag.find(_NAME_TAG)
        if name_el is not None:
            name_el.text = name
        comment_el = tag.find(_COMMENT_TAG)
        if comment_el is not None:
            comment_el.text = comment
        if not address:
            return
        for addr_tag in _ADDRESS_TAGS:
            addr_el = tag.find(addr_tag)
            if addr_el is not None:
                addr_el.text = address
                return

    def _append_after_last_tag(self, new_tag: ET.Element) -> None:
        """Inserta ``new_tag`` tras el ultimo PlcTag hermano si existe."""
        tags = self._root.findall(f".//{_PLC_TAG}")
        last_tag = tags[-1] if tags else None
        if last_tag is not None and last_tag is not new_tag:
            parent = self._find_parent_of(last_tag)
            if parent is not None:
                idx = list(parent).index(last_tag)
                parent.insert(idx + 1, new_tag)
                return
        self._root.append(new_tag)

    def _find_parent_of(
        self, target: ET.Element
    ) -> ET.Element | None:
        """Busca el elemento padre de ``target`` recorriendo el arbol."""
        for parent in self._root.iter():
            for child in list(parent):
                if child is target:
                    return parent
        return None

    # =================================================================
    # PlcUserConstant: add/remove para N_MAX y devices
    # =================================================================
    #
    # Los devices y N_MAX viven como PlcUserConstant en las tag tables
    # (p. ej. 2000_Disp_ED, 000_Config_Dispositivos). El esquema es:
    #   <SW.Tags.PlcUserConstant ID="...">
    #     <AttributeList>
    #       <Name>...</Name>           (plc_tag)
    #       <DataTypeName>Int</DataTypeName>
    #       <Value>5</Value>           (uid / dimension)
    #     </AttributeList>
    #   </SW.Tags.PlcUserConstant>
    #
    # A diferencia de PlcTag (que usa Comment para el uid), PlcUserConstant
    # tiene Value para el uid y Name para el plc_tag. Los siguientes
    # metodos son el equivalente PlcUserConstant de add_tags_by_table /
    # remove_tags / _find_template_tag.

    def _find_template_user_constant(self) -> ET.Element | None:
        """Devuelve el primer ``{*}SW.Tags.PlcUserConstant`` como plantilla."""
        tags = self._root.findall(f".//{_PLC_USER_CONSTANT}")
        return tags[0] if tags else None

    def _existing_user_constant_names(self) -> set[str]:
        """Devuelve el conjunto de ``{*}Name`` ya presentes en PlcUserConstants."""
        result: set[str] = set()
        for const in self._root.findall(f".//{_PLC_USER_CONSTANT}"):
            name_el = const.find(f".//{_NAME_TAG}")
            if name_el is not None and name_el.text:
                result.add(name_el.text.strip())
        return result

    def add_user_constants_by_table(
        self,
        table_name: str,
        dispositivos: list[dict[str, str]],
    ) -> int:
        """Anade PlcUserConstants a la tabla (PlcTagTable) cuyo stem coincide con ``table_name``.

        Cada dict debe contener ``plc_tag`` (el Name) y ``uid`` (el Value).
        ``comment`` es opcional (default: vacio).

        Returns:
            Numero de PlcUserConstants anadidos.
        """
        if self._path.stem != table_name:
            return 0
        template = self._find_template_user_constant()
        if template is None:
            return 0
        existing_names = self._existing_user_constant_names()
        added = 0
        for dto in dispositivos:
            name = dto.get("plc_tag", "").strip()
            if not name or name in existing_names:
                continue
            value_str = dto.get("uid", "").strip()
            comment = dto.get("comment", "").strip()
            new_const = self._copy_element(template)
            name_el = new_const.find(f".//{_NAME_TAG}")
            if name_el is not None:
                name_el.text = name
            value_el = new_const.find(f".//{_VALUE_TAG}")
            if value_el is not None:
                value_el.text = value_str
            if comment:
                self._inject_multilingual_comment(new_const, comment)
            self._append_after_last_user_constant(new_const)
            existing_names.add(name)
            added += 1
        if added > 0:
            self._modified = True
        return added

    def remove_user_constants(self, uids_to_remove: set[str]) -> int:
        """Elimina PlcUserConstants cuyo ``Value`` esta en ``uids_to_remove``.

        Returns:
            Numero de PlcUserConstants eliminados.
        """
        if not uids_to_remove:
            return 0
        removed = 0
        for const in list(self._root.findall(f".//{_PLC_USER_CONSTANT}")):
            value_el = const.find(f".//{_VALUE_TAG}")
            if value_el is None or value_el.text is None:
                continue
            if value_el.text.strip() not in uids_to_remove:
                continue
            parent = self._find_parent_of(const)
            if parent is not None:
                parent.remove(const)
                removed += 1
        if removed > 0:
            self._modified = True
        return removed

    @staticmethod
    def _copy_element(elem: ET.Element) -> ET.Element:
        """Devuelve una copia profunda de un Element."""
        from copy import deepcopy
        return deepcopy(elem)

    def _inject_multilingual_comment(
        self, const: ET.Element, text: str
    ) -> None:
        """Inyecta la estructura canonica Siemens MultilingualText como Comment."""
        comment_local_name = _COMMENT_TAG.split("}", 1)[-1]
        comment_el = const.find(comment_local_name)
        if comment_el is None:
            comment_el = ET.SubElement(const, comment_local_name)
        for child in list(comment_el):
            comment_el.remove(child)
        mlt = ET.SubElement(
            comment_el,
            "MultiLanguageText",
            {"Lang": "es-ES", "CompositionName": "Comment"},
        )
        mlt_ol = ET.SubElement(mlt, "ObjectList")
        mlti = ET.SubElement(
            mlt_ol,
            "MultilingualTextItem",
            {"CompositionName": "Items"},
        )
        mlti_al = ET.SubElement(mlti, "AttributeList")
        ET.SubElement(mlti_al, "Culture").text = "es-ES"
        ET.SubElement(mlti_al, "Text").text = text

    def _append_after_last_user_constant(self, new_const: ET.Element) -> None:
        """Inserta ``new_const`` tras el ultimo PlcUserConstant hermano si existe."""
        consts = self._root.findall(f".//{_PLC_USER_CONSTANT}")
        last = consts[-1] if consts else None
        if last is not None and last is not new_const:
            parent = self._find_parent_of(last)
            if parent is not None:
                idx = list(parent).index(last)
                parent.insert(idx + 1, new_const)
                return
        self._root.append(new_const)