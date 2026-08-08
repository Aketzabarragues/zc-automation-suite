"""Modificadores XML para PlcTagTable (SimaticML).

Clases que clonan nodos ``<SW.Tags.PlcTag>`` de una plantilla, actualizan
las etiquetas de nombre/dirección iterando sobre los DTOs de hardware
y guardan el resultado para importación posterior vía ``import_plc_tags``.

Restricción arquitectónica: este módulo es OFFLINE; no importa
``siemens_tia_scripting``. Usa exclusivamente ``xml.etree.ElementTree``.

Refactor obligatorio: las búsquedas XPath NO usan diccionarios de
namespaces hardcoded; se apoyan en la sintaxis de comodín ``{*}``
introducida en Python 3.8 para ser inmunes a cambios de versión del
esquema SimaticML de Siemens.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from copy import deepcopy
from pathlib import Path
from typing import Any, cast


# Wildcards XPath. ``{*}`` = cualquier namespace; evita acoplarse a la
# versión concreta del esquema (p. ej. ``http://www.siemens.com/...``).
_PLC_TAG = "{*}SW.Tags.PlcTag"
_NAME_TAG = "{*}Name"
# Etiquetas de dirección/defensa: probamos varias conocidas para
# cubrir distintas versiones del esquema.
_ADDRESS_TAGS: tuple[str, ...] = (
    "{*}Address",
    "{*}LogicalAddress",
    "{*}MemoryArea",
)


class XMLModifier:
    """Clase base: carga un XML SimaticML y permite guardarlo."""

    def __init__(self, xml_path: str | Path) -> None:
        self._path = Path(xml_path)
        if not self._path.is_file():
            raise FileNotFoundError(
                f"No se encontró el archivo XML: '{self._path}'"
            )
        # ``ET.parse`` está tipado como ``ElementTree[Element | None]`` por
        # invariancia de generics; en la práctica nunca devuelve None con
        # un archivo XML válido. Usamos Any para silenciar el warning sin
        # perder el tipado fuerte del ``_root``.
        self._tree: Any = ET.parse(str(self._path))
        self._root: ET.Element = cast(ET.Element, self._tree.getroot())

    def save(self, output_path: str | Path) -> None:
        """Escribe el árbol XML modificado en ``output_path``."""
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        self._tree.write(
            str(out), encoding="utf-8", xml_declaration=True
        )


class TagTableModifier(XMLModifier):
    """Modifica una PlcTagTable XML clonando nodos ``<{*}SW.Tags.PlcTag>``.

    La inyección es **idempotente**: si un PlcTag con el mismo nombre
    (``{*}Name``) ya existe, no se vuelve a insertar.
    """

    def add_tags(self, dtos: list[dict[str, Any]]) -> int:
        """Añade PlcTag instances desde una lista de DTOs.

        Cada DTO debe contener al menos ``nombre`` (instance name) y
        opcionalmente ``direccion`` (dirección PLC).

        Returns:
            Número de PlcTag realmente añadidos (idempotente).
        """
        template = self._find_template_tag()
        if template is None:
            return 0

        existing_names = self._existing_tag_names()
        added = 0
        for dto in dtos:
            if not isinstance(dto, dict):
                continue
            name = str(dto.get("nombre", "")).strip()
            if not name or name in existing_names:
                continue
            address = str(dto.get("direccion", "")).strip()
            new_tag = deepcopy(template)
            self._update_tag_fields(new_tag, name=name, address=address)
            # Insertar tras el último PlcTag existente (no tras el root)
            # para respetar el orden lógico del documento.
            self._append_after_last_tag(new_tag)
            existing_names.add(name)
            added += 1
        return added

    def _existing_tag_names(self) -> set[str]:
        """Devuelve el conjunto de nombres ``{*}Name`` ya presentes."""
        result: set[str] = set()
        # ``ET.iter`` NO soporta la sintaxis wildcard ``{*}`` (limitación
        # de Python 3.x). Usamos ``findall(".//{*}...")`` que sí la acepta.
        for tag in self._root.findall(f".//{_PLC_TAG}"):
            name_el = tag.find(_NAME_TAG)
            if name_el is None:
                continue
            txt = (name_el.text or "").strip()
            if txt:
                result.add(txt)
        return result

    def _find_template_tag(self) -> ET.Element | None:
        """Devuelve el primer nodo ``{*}SW.Tags.PlcTag`` como plantilla."""
        tags = self._root.findall(f".//{_PLC_TAG}")
        return tags[0] if tags else None

    @staticmethod
    def _update_tag_fields(
        tag: ET.Element, name: str, address: str
    ) -> None:
        """Actualiza ``{*}Name`` y (opcionalmente) un tag de dirección."""
        name_el = tag.find(_NAME_TAG)
        if name_el is not None:
            name_el.text = name
        if not address:
            return
        for addr_tag in _ADDRESS_TAGS:
            addr_el = tag.find(addr_tag)
            if addr_el is not None:
                addr_el.text = address
                return

    def _append_after_last_tag(self, new_tag: ET.Element) -> None:
        """Inserta ``new_tag`` tras el último PlcTag hermano si existe."""
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
        """Busca el elemento padre de ``target`` recorriendo el árbol."""
        for parent in self._root.iter():
            for child in list(parent):
                if child is target:
                    return parent
        return None
