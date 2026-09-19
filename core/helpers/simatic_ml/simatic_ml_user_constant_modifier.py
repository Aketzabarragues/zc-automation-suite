"""Modificador SimaticML para PlcUserConstant (Siemens TIA Scripting).

Carga un XML SimaticML exportado, permite anadir / eliminar
``<SW.Tags.PlcUserConstant>`` clonando de una plantilla, y guarda el
resultado para importacion posterior via ``import_plc_tags_xml``.

Convenciones del modelo PlcUserConstant:
  - ``<Name>``    <-- ``plc_tag`` (texto, unico por tabla)
  - ``<Value>``   <-- ``uid`` del Excel o dimension N_MAX (entero)
  - ``<Comment>`` <-- descripcion humana (multilingual es-ES)

Restriccion arquitectonica: este modulo es OFFLINE; no importa
``siemens_tia_scripting``. Usa exclusivamente ``xml.etree.ElementTree``.
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, cast

# Asegura que ``Logger.web/ok`` existen tambien fuera del arranque.
from core.infrastructure.log_web_bridge import install_web_level

from core.helpers.simatic_ml.simatic_ml_constants import (
    COMMENT_TAG,
    NAME_TAG,
    USER_CONSTANT_TAG,
    VALUE_TAG,
)

install_web_level()

_logger = logging.getLogger(__name__)


class PlcUserConstantModifier:
    """Carga un XML SimaticML y permite mutar PlcUserConstants.

    Inyeccion idempotente: si un PlcUserConstant con el mismo
    ``<Name>`` ya existe, no se vuelve a insertar.

    Convenciones:
      - ``Name``    <-- ``dispositivo.plc_tag``
      - ``Value``   <-- ``dispositivo.uid`` (mapeo IT para diff)
      - ``Comment`` <-- descripcion humana opcional
    """

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

    # =================================================================
    # PlcUserConstant: add/remove para N_MAX y devices
    # =================================================================
    #
    # Los devices y N_MAX viven como PlcUserConstant en las tag tables
    # (p.ej. 2000_Disp_ED, 000_Config_Dispositivos). El esquema es:
    #   <SW.Tags.PlcUserConstant ID="...">
    #     <AttributeList>
    #       <Name>...</Name>           (plc_tag)
    #       <DataTypeName>Int</DataTypeName>
    #       <Value>5</Value>           (uid / dimension)
    #     </AttributeList>
    #   </SW.Tags.PlcUserConstant>

    def read_user_constants_with_uids(self) -> dict[str, str]:
        """Itera PlcUserConstants y devuelve ``{value_str: plc_tag}``.

        Shape invertido vs ``PlcUserConstantParser.parse_user_constants``
        (que devuelve ``{name: value_int}``): aqui la clave es el
        ``<Value>`` (string) y el valor es el ``<Name>`` (plc_tag).
        El caller (preview de dispositivos) necesita este shape
        para hacer el diff contra el Excel.

        Solo incluye constantes casteables a int (igual que el
        parser).
        """
        result: dict[str, str] = {}
        for const in self._root.findall(f".//{USER_CONSTANT_TAG}"):
            name_el = const.find(f".//{NAME_TAG}")
            value_el = const.find(f".//{VALUE_TAG}")
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

    def _find_template_user_constant(self) -> ET.Element | None:
        """Devuelve el primer PlcUserConstant del documento como plantilla."""
        tags = self._root.findall(f".//{USER_CONSTANT_TAG}")
        return tags[0] if tags else None

    def _existing_user_constant_names(self) -> set[str]:
        """Devuelve el conjunto de ``<Name>`` ya presentes."""
        result: set[str] = set()
        for const in self._root.findall(f".//{USER_CONSTANT_TAG}"):
            name_el = const.find(f".//{NAME_TAG}")
            if name_el is not None and name_el.text:
                result.add(name_el.text.strip())
        return result

    def add_user_constants_by_table(
        self,
        table_name: str,
        dispositivos: list[dict[str, str]],
    ) -> int:
        """Anade PlcUserConstants a la tabla cuyo stem coincide con ``table_name``.

        Convencion: el archivo XML se llama igual que la tabla TIA
        (p.ej. ``2000_Disp_ED.xml`` para la tabla ``2000_Disp_ED``).
        Si el stem no coincide, no se hace nada (devuelve 0).

        Cada dict debe contener ``plc_tag`` (el Name) y ``uid`` (el Value).
        ``comment`` es opcional (default: vacio).

        Returns:
            Numero de PlcUserConstants anadidos.
        """
        stem_match = self._path.stem == table_name
        _logger.debug(
            f"PlcUserConstantModifier.add_user_constants_by_table: "
            f"table={table_name!r} ({len(dispositivos)} disp, "
            f"stem_match={stem_match}, file={self._path.name})"
        )
        if not stem_match:
            return 0
        template = self._find_template_user_constant()
        if template is None:
            _logger.warning(
                f"PlcUserConstantModifier: no template PlcUserConstant "
                f"encontrado en '{self._path.name}', 0 anadidos"
            )
            return 0
        existing_names = self._existing_user_constant_names()
        added = 0
        # max_id se actualiza despues de CADA add, para que el siguiente
        # nuevo constant empiece DESPUES de los IDs ya asignados. Sin
        # esto, dos adds consecutivos comparten los mismos IDs y TIA V21
        # rechaza el import con "Duplicate Simatic ML ID".
        max_id = self._max_id_in_doc()
        for dto in dispositivos:
            name = dto.get("plc_tag", "").strip()
            if not name or name in existing_names:
                continue
            value_str = dto.get("uid", "").strip()
            comment = dto.get("comment", "").strip()
            new_const = self._copy_element(template)
            # CRITICO: renumerar TODOS los IDs del subtree del nuevo
            # constant. Si no, los nuevos elementos tienen los mismos
            # IDs que el template (p.ej. "1", "2", "3"...) y TIA V21
            # rechaza el import con "Duplicate Simatic ML ID".
            ids_in_subtree = sum(
                1 for sub in new_const.iter() if "ID" in sub.attrib
            )
            self._renumber_ids(new_const, start=max_id + 1)
            max_id += ids_in_subtree
            name_el = new_const.find(f".//{NAME_TAG}")
            if name_el is not None:
                name_el.text = name
            value_el = new_const.find(f".//{VALUE_TAG}")
            if value_el is not None:
                value_el.text = value_str
            if comment:
                self._inject_multilingual_comment(new_const, comment)
            self._append_after_last_user_constant(new_const)
            existing_names.add(name)
            added += 1
        if added > 0:
            self._modified = True
        _logger.debug(
            f"PlcUserConstantModifier: +{added} anadidos en '{table_name}' "
            f"(de {len(dispositivos)} solicitados)"
        )
        return added

    def _max_id_in_doc(self) -> int:
        """Devuelve el maximo ID numerico usado en el documento.

        Recorre todos los elementos y devuelve el maximo valor del
        atributo ``ID`` que sea convertible a int. Si no hay IDs
        numericos, devuelve -1.

        IMPORTANTE: Siemens exporta los IDs en hexadecimal MAYUSCULA sin
        prefijo (``"0"``, ``"1"``, ``"A"``, ``"FF"``...). Usar
        ``int(id_str, 0)`` es un BUG porque solo acepta hex con prefijo
        ``0x``; los IDs ``"A"``/``"B"``/``"C"`` se ignoran y el calculo
        se queda corto, colisionando con los nuevos constants.
        """
        max_id = -1
        for elem in self._root.iter():
            id_str = elem.get("ID", "")
            if not id_str:
                continue
            try:
                # Siemens siempre emite hex mayuscula sin prefijo.
                # ``int(x, 16)`` acepta tanto ``"0"`` (decimal==hex==0) como
                # ``"A"``/``"FF"``. Si el esquema cambiase a decimal/otro,
                # el ``except`` lo descartaria silenciosamente.
                id_int = int(id_str, 16)
                if id_int > max_id:
                    max_id = id_int
            except (ValueError, TypeError):
                continue
        return max_id

    @staticmethod
    def _renumber_ids(elem: ET.Element, start: int) -> None:
        """Renumera todos los atributos ``ID`` del subtree de ``elem``.

        Asigna IDs correlativos empezando en ``start`` (start, start+1,
        start+2, ...) en orden de documento. Esto evita colisiones
        con los IDs existentes cuando se inserta un nuevo constant
        clonado del template.
        """
        next_id = start
        for sub in elem.iter():
            if "ID" in sub.attrib:
                sub.set("ID", f"{next_id:x}".upper())  # hex mayusculas (formato Siemens)
                next_id += 1

    def remove_user_constants(self, uids_to_remove: set[str]) -> int:
        """Elimina PlcUserConstants cuyo ``<Value>`` esta en ``uids_to_remove``.

        Returns:
            Numero de PlcUserConstants eliminados.
        """
        if not uids_to_remove:
            return 0
        _logger.debug(
            f"PlcUserConstantModifier.remove_user_constants: "
            f"{len(uids_to_remove)} uids a eliminar de '{self._path.name}'"
        )
        removed = 0
        for const in list(self._root.findall(f".//{USER_CONSTANT_TAG}")):
            value_el = const.find(f".//{VALUE_TAG}")
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
        _logger.debug(
            f"PlcUserConstantModifier: -{removed} eliminados de "
            f"'{self._path.name}' (de {len(uids_to_remove)} solicitados)"
        )
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
        comment_local_name = COMMENT_TAG.split("}", 1)[-1]
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
        consts = self._root.findall(f".//{USER_CONSTANT_TAG}")
        last = consts[-1] if consts else None
        if last is not None and last is not new_const:
            parent = self._find_parent_of(last)
            if parent is not None:
                idx = list(parent).index(last)
                parent.insert(idx + 1, new_const)
                return
        self._root.append(new_const)

    def _find_parent_of(
        self, target: ET.Element
    ) -> ET.Element | None:
        """Busca el elemento padre de ``target`` recorriendo el arbol."""
        for parent in self._root.iter():
            for child in list(parent):
                if child is target:
                    return parent
        return None
