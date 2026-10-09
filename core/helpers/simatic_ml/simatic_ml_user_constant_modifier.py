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
from core.infrastructure.log.log_web_bridge import install_web_level

from core.helpers.simatic_ml.simatic_ml_constants import (
    COMMENT_TAG,
    MULTI_LINGUAL_TEXT_TAG,
    NAME_TAG,
    OBJECT_LIST_TAG,
    TEXT_TAG,
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

    def read_user_constants_with_comments(self) -> dict[str, dict[str, str | None]]:
        """Itera PlcUserConstants y devuelve ``{value_str: {"name", "comment"}}``.

        Igual que ``read_user_constants_with_uids`` pero captura
        tambien el ``<Comment>`` per-constant (primer
        ``<MultilingualTextItem>/<Text>``). ``comment`` es ``None`` si
        la constant existe sin comment inicializado o con texto vacio.

        Usado por el preview de entidades (C.25): el comment per-constant
        tiene prioridad sobre el comment del slot del DB a la hora de
        comparar TIA vs Excel en el diff unificado. El operario suele
        configurar el comment en la tabla de constantes, no en el slot
        del array del DB.
        """
        result: dict[str, dict[str, str | None]] = {}
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
            comment: str | None = None
            mlti = const.find(".//{*}MultilingualTextItem")
            if mlti is not None:
                text_el = mlti.find(".//{*}Text")
                if text_el is not None and text_el.text:
                    stripped = text_el.text.strip()
                    if stripped:
                        comment = stripped
            result[value] = {"name": name, "comment": comment}
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

    def remove_user_constants_by_name(self, names_to_remove: set[str]) -> int:
        """Elimina PlcUserConstants cuyo ``<Name>`` esta en ``names_to_remove``.

        Variante de ``remove_user_constants`` (que opera por <Value>):
        aqui el match es por el plc_tag canonico del Excel. Usado por
        el sync de entidades (D.2) para borrar las PlcConstants
        marcadas como ``eliminar`` en el diff unificado.

        Returns:
            Numero de PlcUserConstants eliminados.
        """
        if not names_to_remove:
            return 0
        _logger.debug(
            f"PlcUserConstantModifier.remove_user_constants_by_name: "
            f"{len(names_to_remove)} names a eliminar de '{self._path.name}'"
        )
        removed = 0
        for const in list(self._root.findall(f".//{USER_CONSTANT_TAG}")):
            name_el = const.find(f".//{NAME_TAG}")
            if name_el is None or name_el.text is None:
                continue
            if name_el.text.strip() not in names_to_remove:
                continue
            parent = self._find_parent_of(const)
            if parent is not None:
                parent.remove(const)
                removed += 1
        if removed > 0:
            self._modified = True
        _logger.debug(
            f"PlcUserConstantModifier.remove_user_constants_by_name: "
            f"-{removed} eliminados de '{self._path.name}'"
        )
        return removed

    def update_user_constant_comment(self, plc_name: str, comment: str) -> bool:
        """Actualiza el ``<Comment>`` per-constant del PlcUserConstant.

        True si encontro y modifico la constant. False si no existe.
        Wrapper publico de ``_inject_multilingual_comment`` para uso
        desde los FBs de sync (D.2).

        Args:
            plc_name: ``<Name>`` de la PlcUserConstant a actualizar.
            comment: nuevo texto (string vacio ``""`` = limpiar comment).

        Returns:
            True si modifico la constant, False si no la encontro.
        """
        for const in self._root.findall(f".//{USER_CONSTANT_TAG}"):
            name_el = const.find(f".//{NAME_TAG}")
            if name_el is None or name_el.text is None:
                continue
            if name_el.text.strip() != plc_name:
                continue
            self._inject_multilingual_comment(const, comment)
            self._modified = True
            _logger.debug(
                f"PlcUserConstantModifier.update_user_constant_comment: "
                f"'{plc_name}' comment actualizado en '{self._path.name}'"
            )
            return True
        _logger.warning(
            f"PlcUserConstantModifier.update_user_constant_comment: "
            f"'{plc_name}' no encontrado en '{self._path.name}'"
        )
        return False

    def update_user_constant_value_by_name(self, plc_name: str, new_value: int) -> bool:
        """Actualiza el ``<Value>`` del PlcUserConstant identificado por ``<Name>``.

        True si encontro y modifico la constant. False si no existe.
        Variante offline de ``_h_update_user_constant_value`` (TIA Portal
        online): opera directamente en el XML FLAT. Usado por stage 7
        (D.4) del sync de entidades para el NMAX (aunque el NMAX
        normalmente va por Tx A online en stage 4).

        Args:
            plc_name: ``<Name>`` de la PlcUserConstant a actualizar.
            new_value: nuevo ``<Value>``.

        Returns:
            True si modifico, False si no encontro.
        """
        for const in self._root.findall(f".//{USER_CONSTANT_TAG}"):
            name_el = const.find(f".//{NAME_TAG}")
            if name_el is None or name_el.text is None:
                continue
            if name_el.text.strip() != plc_name:
                continue
            value_el = const.find(f".//{VALUE_TAG}")
            if value_el is None:
                continue
            value_el.text = str(int(new_value))
            self._modified = True
            _logger.debug(
                f"PlcUserConstantModifier.update_user_constant_value_by_name: "
                f"'{plc_name}' value -> {new_value} en '{self._path.name}'"
            )
            return True
        _logger.warning(
            f"PlcUserConstantModifier.update_user_constant_value_by_name: "
            f"'{plc_name}' no encontrado en '{self._path.name}'"
        )
        return False

    @staticmethod
    def _copy_element(elem: ET.Element) -> ET.Element:
        """Devuelve una copia profunda de un Element."""
        from copy import deepcopy
        return deepcopy(elem)

    def _inject_multilingual_comment(
        self, const: ET.Element, text: str
    ) -> None:
        """Inyecta/actualiza el comment per-constant en la jerarquia canonica Siemens.

        TIA V21 espera el comment DENTRO del ``<ObjectList>`` del
        ``PlcUserConstant``, NO como hijo directo. Estructura canonica:

            <PlcUserConstant>
              <AttributeList>...</AttributeList>
              <ObjectList>
                <MultilingualText CompositionName="Comment">
                  <ObjectList>
                    <MultilingualTextItem>
                      <AttributeList>
                        <Culture>es-ES</Culture>
                        <Text>{text}</Text>
                      </AttributeList>
                    </MultilingualTextItem>
                  </ObjectList>
                </MultilingualText>
              </ObjectList>
            </PlcUserConstant>

        Antes del fix (C.7.9), el helper creaba un ``<Comment>`` hermano
        de ``<AttributeList>`` y ``<ObjectList>`` — eso es XML
        estructuralmente invalido para V21, que rechaza con
        ``OpennessAccessException: CommitOnDispose`` al hacer el
        ``import_plc_tags_xml``.

        Comportamiento:
          - Si el constant ya tiene un ``<MultilingualText
            CompositionName="Comment">`` dentro de su ``<ObjectList>``:
            reemplaza el ``<Text>`` del primer
            ``<MultilingualTextItem>`` (preserva el resto de la
            estructura).
          - Si no lo tiene: crea la estructura canonica DENTRO del
            ``<ObjectList>`` existente.
          - ``text`` vacio ``""``: deja ``<Text />`` (vacio, no elimina
          la entrada).

        Raises:
          RuntimeError: si el constant no tiene ``<ObjectList>``
            (estructura corrupta del template).
        """
        object_list_local = OBJECT_LIST_TAG.split("}", 1)[-1]
        multi_text_local = MULTI_LINGUAL_TEXT_TAG.split("}", 1)[-1]
        text_local = TEXT_TAG.split("}", 1)[-1]

        # Buscar <ObjectList> hijo directo. element.find() requiere el
        # nombre con namespace completo; usamos XPath wildcard para
        # soportar tanto ``{*}ObjectList`` como ``{ns}ObjectList``.
        object_list = const.find(f"./{OBJECT_LIST_TAG}")
        if object_list is None:
            # Tolerar template sin ObjectList (e.g. tests): crearlo
            # antes de inyectar el comment. En TIA real los constants
            # SIEMPRE tienen ObjectList; esto es solo defensa.
            name_text = ""
            name_el = const.find(NAME_TAG)
            if name_el is not None:
                name_text = str(name_el.text or "")
            # Usar el mismo namespace que el padre.
            local_ns = (
                const.tag.split("}", 1)[0] + "}"
                if "}" in const.tag else ""
            )
            object_list = ET.SubElement(const, local_ns + object_list_local)
            _logger.debug(
                f"PlcUserConstantModifier._inject_multilingual_comment: "
                f"constant '{name_text}' no tenia <ObjectList>; creado"
            )

        # Buscar/crear <MultilingualText CompositionName="Comment">
        # DENTRO de <ObjectList>. child.tag incluye el namespace
        # completo (e.g. ``{http://...}MultilingualText``); comparar
        # solo el local name (parte tras ``}``) o usar wildcard XPath.
        mlt = None
        for child in object_list:
            local = child.tag.split("}", 1)[-1] if "}" in child.tag else child.tag
            if local == multi_text_local and child.get(
                "CompositionName", ""
            ) == "Comment":
                mlt = child
                break

        if mlt is None:
            # Crear la estructura canonica DENTRO de <ObjectList>.
            # Usar el mismo namespace que el padre para consistencia.
            local_ns = (
                object_list.tag.split("}", 1)[0] + "}"
                if "}" in object_list.tag else ""
            )
            mlt = ET.SubElement(
                object_list,
                local_ns + multi_text_local,
                {"CompositionName": "Comment"},
            )
            mlt_inner_ol = ET.SubElement(mlt, local_ns + object_list_local)
            mlti = ET.SubElement(
                mlt_inner_ol,
                local_ns + "MultilingualTextItem",
                {"CompositionName": "Items"},
            )
            mlti_al = ET.SubElement(mlti, local_ns + "AttributeList")
            ET.SubElement(mlti_al, local_ns + "Culture").text = "es-ES"
            text_el = ET.SubElement(mlti_al, local_ns + text_local)
        else:
            # Reusar el primer <MultilingualTextItem> existente.
            # Usar wildcard XPath porque element.find() requiere el
            # nombre con namespace completo para matchear.
            mlti = mlt.find(f"{OBJECT_LIST_TAG}/MultilingualTextItem")
            if mlti is None:
                # Tag local: usar el mismo namespace que mlt (heredado).
                local_ns = mlt.tag.split("}", 1)[0] + "}" if "}" in mlt.tag else ""
                mlt_inner_ol = ET.SubElement(mlt, local_ns + object_list_local)
                mlti = ET.SubElement(
                    mlt_inner_ol,
                    local_ns + "MultilingualTextItem",
                    {"CompositionName": "Items"},
                )
                mlti_al = ET.SubElement(mlti, local_ns + "AttributeList")
                ET.SubElement(mlti_al, local_ns + "Culture").text = "es-ES"
                text_el = ET.SubElement(mlti_al, local_ns + text_local)
            else:
                text_el = mlti.find(f"AttributeList/{TEXT_TAG}")
                if text_el is None:
                    text_el = ET.SubElement(
                        mlti.find(f"AttributeList"),
                        text_local,
                    )
        # Actualizar el texto (string vacio = limpiar).
        text_el.text = text if text else None

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
