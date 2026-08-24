"""Modificador offline de PlcTagTable: añade PlcUserConstant nuevas.

Replica moderna del ``TagTableModifier`` legacy (``add_user_constant``).
Construye la estructura canónica completa de Siemens:

    <SW.Tags.PlcUserConstant ID="1" CompositionName="UserConstants">
      <AttributeList>
        <Name>...</Name>
        <DataTypeName>Int</DataTypeName>
        <Value>5</Value>
        <Comment>
          <MultiLanguageText Lang="es-ES">...</MultiLanguageText>
        </Comment>
      </AttributeList>
      <ObjectList>
        <SW.Tags.PlcUserConstant ID="1E" CompositionName="Instances">
          <AttributeList>
            <Name>...</Name>
          </AttributeList>
        </SW.Tags.PlcUserConstant>
      </ObjectList>
      <LinkList />
    </SW.Tags.PlcUserConstant>

Restricción arquitectónica: este módulo es OFFLINE; no importa
``siemens_tia_scripting``. Solo usa la stdlib (``pathlib`` y ``xml.etree``).

Convenciones heredadas del legacy:
  - IDs en formato Siemens: hexadecimal MAYÚSCULA puro (``"1A"``, ``"2F"``).
  - NO prefijo ``0x`` ni padding a 8 chars.
  - IDs únicos por documento (constante + MultilingualText + MultilingualTextItem
    cada uno con su propio ID monotónicamente creciente).
  - Inserción de ``<ObjectList>`` en posición canónica (justo después de
    ``<AttributeList>``), nunca al final, para evitar que TIA rechace la
    importación con error críptico del COM.
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, cast


_logger: logging.Logger = logging.getLogger(f"{__name__}.UserConstantsModifier")


_DEFAULT_DATA_TYPE = "Int"
_DEFAULT_LANG = "es-ES"
_DEFAULT_COMPOSITION = "UserConstants"


def _local(tag: str) -> str:
    """Devuelve el nombre local de un tag (sin namespace ni prefijo Siemens).

    Soporta dos formatos:
    - Clark notation: ``{http://...}PlcTagTable`` -> ``PlcTagTable``.
    - Prefijo Siemens: ``SW.Tags.PlcTagTable`` -> ``PlcTagTable``.

    El formato de export de TIA Portal V1.2.1 NO incluye declaracion
    ``xmlns``; los tags usan el prefijo ``SW.Tags.`` directamente. Ver
    ``_legacy_reference/ZC_ALM_TOOLS/infrastructure/xml/tag_modifier.py:25-27``.
    """
    if "}" in tag:
        return tag.split("}", 1)[-1]
    if tag.startswith("SW.Tags."):
        return tag[len("SW.Tags."):]
    return tag


class UserConstantsModifier:
    """Editor offline de PlcTagTable: añade PlcUserConstant nuevas.

    Estrategia:
      1. Lee el XML con ``xml.etree.ElementTree`` (preserva orden y namespaces).
      2. Calcula el siguiente ID hexadecimal disponible.
      3. Para cada ``add_user_constant(name, value, comment)``, construye el
         subárbol canónico con sus propios IDs únicos.
      4. ``save()`` persiste el árbol en disco.
    """

    def __init__(self, xml_path: str | Path) -> None:
        self._path = Path(xml_path)
        if not self._path.is_file():
            raise FileNotFoundError(
                f"No se encontró el archivo PlcTagTable: '{self._path}'"
            )
        # ``ET.parse`` está tipado como ``ElementTree[Element | None]`` por
        # invariancia de generics; en la práctica nunca devuelve None con
        # un archivo XML válido. Usamos ``Any`` + ``cast`` (ver tabla_injector).
        self._tree: Any = ET.parse(str(self._path))
        self._root: ET.Element = cast(ET.Element, self._tree.getroot())
        self._max_id: int = self._compute_max_id()
        self._object_list: ET.Element | None = self._find_object_list()
        self._modified: bool = False

    # ── API pública ────────────────────────────────────────────────────

    def add_user_constant(
        self,
        name: str,
        value: int,
        comment: str = "",
    ) -> bool:
        """Añade un nuevo ``SW.Tags.PlcUserConstant`` al ``<ObjectList>``.

        Args:
            name:    Nombre simbólico de la constante (ej. ``"V_VA_101"``).
            value:   Valor entero (debe ser casteable a ``int``).
            comment: Comentario multilenguaje (opcional).

        Returns:
            ``True`` si la constante fue añadida, ``False`` si ya existía
            (idempotencia: no duplica por nombre).
        """
        if not name:
            raise ValueError("El nombre de la constante no puede estar vacío.")

        if self._find_constant_by_name(name) is not None:
            _logger.debug(
                f"Constante '{name}' ya existe en la tabla (idempotente). "
                "Se omite add_user_constant()."
            )
            return False

        object_list = self._ensure_object_list()
        if object_list is None:
            _logger.error(
                f"No se encontró contenedor PlcUserConstantTable/PlcTagTable "
                f"en '{self._path}'. Xml no es una PlcTagTable válida."
            )
            return False

        # Asignar IDs hexadecimales únicos para los 3 elementos canónicos:
        #   1. PlcUserConstant raíz
        #   2. MultilingualText (Comment)
        #   3. MultilingualTextItem (Text dentro de Comment)
        const_id = self._next_id_hex()
        mlt_id = self._next_id_hex() if comment else "N/A"
        mlti_id = self._next_id_hex() if comment else "N/A"

        # Construir el nodo raíz PlcUserConstant.
        constant_node = ET.Element(
            "SW.Tags.PlcUserConstant",
            {"ID": const_id, "CompositionName": _DEFAULT_COMPOSITION},
        )
        attr_list = ET.SubElement(constant_node, "AttributeList")
        ET.SubElement(attr_list, "Name").text = str(name)
        ET.SubElement(attr_list, "DataTypeName").text = _DEFAULT_DATA_TYPE
        ET.SubElement(attr_list, "Value").text = str(int(value))

        if comment:
            obj_list_inner = ET.SubElement(constant_node, "ObjectList")
            mlt = ET.SubElement(
                obj_list_inner,
                "MultilingualText",
                {"ID": mlt_id, "CompositionName": "Comment"},
            )
            mlt_obj_list = ET.SubElement(mlt, "ObjectList")
            mlti = ET.SubElement(
                mlt_obj_list,
                "MultilingualTextItem",
                {"ID": mlti_id, "CompositionName": "Items"},
            )
            mlti_attr_list = ET.SubElement(mlti, "AttributeList")
            ET.SubElement(mlti_attr_list, "Culture").text = _DEFAULT_LANG
            ET.SubElement(mlti_attr_list, "Text").text = str(comment)

        object_list.append(constant_node)
        self._modified = True

        _logger.debug(
            f"Constante '{name}' (value={value}) añadida con estructura canónica. "
            f"IDs: const={const_id}, mlt={mlt_id}, mlti={mlti_id}."
        )
        return True

    def was_modified(self) -> bool:
        """``True`` si ``add_user_constant`` mutó el árbol desde la carga."""
        return self._modified

    def save(self, output_path: str | Path | None = None) -> None:
        """Persiste el árbol modificado.

        Args:
            output_path: ruta destino. Si ``None``, sobreescribe el archivo
                original cargado.
        """
        out = Path(output_path) if output_path else self._path
        out.parent.mkdir(parents=True, exist_ok=True)
        self._tree.write(
            str(out),
            encoding="utf-8",
            xml_declaration=True,
            method="xml",
        )
        _logger.info(f"PlcTagTable guardada en: {out}")

    # ── Internos ───────────────────────────────────────────────────────

    def _compute_max_id(self) -> int:
        """Recorre todos los ``ID="..."`` del XML y devuelve el máximo entero.

        Convierte a uppercase antes de parsear por si vienen en minúsculas.
        Ignora silenciosamente los valores no hexadecimales.
        """
        max_id = -1
        for elem in self._root.iter():
            for attr, value in elem.attrib.items():
                if _local(attr) == "ID" and value:
                    try:
                        max_id = max(max_id, int(value, 16))
                    except ValueError:
                        _logger.debug(
                            f"Atributo ID con valor no hex ignorado: {value!r}"
                        )
        return max_id

    def _next_id_int(self) -> int:
        """Avanza el contador y devuelve el siguiente entero."""
        self._max_id += 1
        return self._max_id

    def _next_id_hex(self) -> str:
        """Genera un nuevo ID en formato Siemens (hex mayúscula PURO)."""
        return f"{self._next_id_int():X}"

    def _find_object_list(self) -> ET.Element | None:
        """Busca el ``<ObjectList>`` hijo directo del contenedor principal.

        Fallback: primer ``<ObjectList>`` del documento.
        """
        for child in self._root:
            if _local(child.tag) == "ObjectList":
                return child
        for elem in self._root.iter():
            if _local(elem.tag) == "ObjectList":
                return elem
        return None

    def _ensure_object_list(self) -> ET.Element | None:
        """Busca un ``<ObjectList>`` o lo crea bajo el contenedor principal.

        CRÍTICO: TIA Portal es ESTRICTO con el orden canónico de los nodos
        XML dentro de PlcTagTable / PlcUserConstantTable:
            ``<AttributeList> ... <ObjectList> ... <LinkList> ...``
        Si creamos ``<ObjectList>`` con ``append`` (al final), rompemos la
        validación COM y TIA rechaza la importación. Por eso lo insertamos
        en la posición 1 (justo después de ``<AttributeList>``) si existe.
        """
        if self._object_list is not None:
            return self._object_list

        # Buscar contenedor principal.
        container: ET.Element | None = None
        for node in self._root.iter():
            if (
                _local(node.tag) == "PlcUserConstantTable"
                or _local(node.tag) == "PlcTagTable"
            ):
                container = node
                break

        if container is None:
            _logger.error(
                f"No se encontró contenedor PlcUserConstantTable/PlcTagTable "
                f"en '{self._path}'."
            )
            return None

        object_list = ET.Element("ObjectList")
        # Posición canónica: tras AttributeList.
        attribute_list_idx: int | None = None
        for idx, child in enumerate(list(container)):
            if _local(child.tag) == "AttributeList":
                attribute_list_idx = idx
                break
        if attribute_list_idx is not None:
            container.insert(attribute_list_idx + 1, object_list)
            _logger.debug(
                "<ObjectList> creado e insertado tras <AttributeList> "
                "(orden canónico TIA)."
            )
        else:
            container.append(object_list)
            _logger.debug(
                "<ObjectList> creado al final (container sin AttributeList hijo)."
            )

        self._object_list = object_list
        return object_list

    def _find_constant_by_name(self, name: str) -> ET.Element | None:
        """Busca una PlcUserConstant existente por ``<Name>``."""
        for constant in self._root.iter():
            if _local(constant.tag) != "PlcUserConstant":
                continue
            attr_list = constant.find("AttributeList")
            if attr_list is None:
                continue
            name_el = attr_list.find("Name")
            if name_el is not None and (name_el.text or "").strip() == name:
                return constant
        return None


__all__ = ["UserConstantsModifier"]
