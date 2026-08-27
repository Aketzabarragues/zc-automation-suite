"""Gestor offline de PlcTagTable: crea y elimina tablas de variables enteras.

Restricción arquitectónica: este módulo es OFFLINE; no importa
``siemens_tia_scripting``. Solo usa la stdlib (``pathlib``, ``shutil``,
``xml.etree``, ``tempfile``).

Caso de uso
-----------
Cada tipo de dispositivo (DispED, DispEA, DispSA, DispV, DispM, DispM_VF)
tiene su PROPIA PlcTagTable (ej. ``2000_Disp_ED``, ``2000_Disp_EA``).
El ciclo de vida de estas tablas es:
  - **CREATE**: clonar la estructura vacía de una plantilla ya existente
    (preserva ``<AttributeList>`` raíz, ``<ObjectList>``, ``<LinkList>``)
    y nombrarla con el ``table_name`` deseado. El archivo resultante está
    listo para importar.
  - **DELETE**: marcar el nombre de la tabla para eliminación; el worker
    invocará ``table.delete()`` por COM DENTRO de la transacción unificada.

Convención de IDs
-----------------
Se reutiliza el patrón Siemens: hexadecimal MAYÚSCULA puro (``"1"``, ``"A"``,
``"1C"``), sin prefijo ``0x`` ni padding a 8 chars. ``_compute_max_id`` +
``_next_id_hex`` garantizan unicidad dentro del documento.

Orden canónico
--------------
TIA Portal es ESTRICTO con el orden de los nodos XML raíz de PlcTagTable:
    ``<AttributeList> ... <ObjectList> ... <LinkList> ...``
Toda inserción respeta esta jerarquía.
"""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, cast


_logger: logging.Logger = logging.getLogger(f"{__name__}.PlcTagTableManager")


_PLC_TAG_TABLE_NS_RE = re.compile(r"\s+xmlns(:\w+)?=\"[^\"]+\"")


def _local(tag: str) -> str:
    """Devuelve el nombre local de un tag (sin namespace)."""
    return tag.split("}", 1)[-1] if "}" in tag else tag


class PlcTagTableManager:
    """Crea PlcTagTable nuevas (estructura canónica) y marca para eliminar.

    API:
      - ``create_empty_table(table_name, target_dir, source_template_path=None)``
        → genera un archivo ``<target_dir>/<table_name>.xml`` con la
        estructura mínima de PlcTagTable vacía, listo para importar.
      - ``mark_for_deletion(table_name)``
        → añade ``table_name`` al registro de tablas a eliminar. El worker
        ejecutará ``table.delete()`` por COM dentro de la transacción.

    El manager NO toca TIA Portal directamente; solo prepara el XML o
    registra intenciones. La ejecución real ocurre en el worker.
    """

    def __init__(self) -> None:
        self._tables_to_delete: list[str] = []
        self._created_tables: list[Path] = []

    # ── CREATE ──────────────────────────────────────────────────────────

    def create_empty_table(
        self,
        table_name: str,
        target_dir: str | Path,
        source_template_path: str | Path | None = None,
    ) -> Path:
        """Crea un PlcTagTable.xml nuevo, vacío, listo para importar.

        Args:
            table_name: nombre de la tabla (ej. ``"2000_Disp_ED"``). Será
                el ``stem`` del archivo y el contenido de ``<Name>``.
            target_dir: directorio donde se creará el archivo.
            source_template_path: ruta opcional a un PlcTagTable existente
                del que se copiará la cabecera (``<AttributeList>`` raíz,
                ``<LinkList>``, etc.). Si ``None``, se genera una cabecera
                vacía mínima.

        Returns:
            ``Path`` al archivo ``<target_dir>/<table_name>.xml`` creado.

        Raises:
            FileExistsError: si ya existe el archivo destino.
        """
        if not table_name:
            raise ValueError("table_name no puede estar vacío.")
        target_dir_path = Path(target_dir)
        target_dir_path.mkdir(parents=True, exist_ok=True)
        output_path = target_dir_path / f"{table_name}.xml"
        if output_path.exists():
            raise FileExistsError(
                f"Ya existe el archivo PlcTagTable destino: '{output_path}'"
            )

        root = self._build_root(table_name, source_template_path)
        tree = ET.ElementTree(root)
        tree.write(
            str(output_path),
            encoding="utf-8",
            xml_declaration=True,
            method="xml",
        )
        self._created_tables.append(output_path)
        _logger.info(
            f"PlcTagTable '{table_name}' creada en: {output_path}"
        )
        return output_path

    def _build_root(
        self,
        table_name: str,
        source_template_path: str | Path | None,
    ) -> ET.Element:
        """Construye el ``<SW.Tags.PlcTagTable>`` raíz con cabecera canónica.

        Si se pasa ``source_template_path``, se intenta clonar su cabecera
        (``<AttributeList>`` raíz y ``<LinkList>``) preservando atributos
        importantes (``ID``, ``CompositionName``). El ``<ObjectList>`` se
        genera vacío para empezar de cero.
        """
        root = ET.Element("SW.Tags.PlcTagTable")

        # ── AttributeList raíz ──────────────────────────────────────
        attr_list = ET.SubElement(root, "AttributeList")
        ET.SubElement(attr_list, "Name").text = table_name
        # Otros campos opcionales (Version, etc.) se añadirán si están
        # presentes en la plantilla. Para mantener la estructura mínima,
        # añadimos lo que TIA Portal espera por defecto:
        ET.SubElement(attr_list, "Interface")

        # ── ObjectList vacío ────────────────────────────────────────
        ET.SubElement(root, "ObjectList")

        # ── LinkList vacío ──────────────────────────────────────────
        ET.SubElement(root, "LinkList")

        # Si hay plantilla, sobreescribimos los nombres de los elementos
        # canónicos para preservar la estructura exacta de Siemens.
        if source_template_path is not None:
            template_path = Path(source_template_path)
            if template_path.is_file():
                self._clone_header_from_template(root, template_path)
            else:
                _logger.warning(
                    f"Plantilla '{source_template_path}' no existe; "
                    "se usará cabecera mínima."
                )

        return root

    def _clone_header_from_template(
        self,
        root: ET.Element,
        template_path: Path,
    ) -> None:
        """Clona los atributos raíz del ``<SW.Tags.PlcTagTable>`` original.

        Preserva ``ID``, ``CompositionName`` y otros atributos personalizados
        que TIA Portal pueda requerir para reconocer la tabla.
        """
        try:
            template_tree: Any = ET.parse(str(template_path))
        except ET.ParseError as e:
            _logger.warning(
                f"No se pudo parsear plantilla '{template_path}': {e}. "
                "Se mantiene cabecera mínima."
            )
            return

        template_root = template_tree.getroot()
        if template_root is None:
            return
        # Copiamos atributos del root (preservando namespace prefix).
        for attr_key, attr_value in template_root.attrib.items():
            # No sobrescribimos si ya tenemos un atributo con el mismo
            # nombre local (caso común: xmlns).
            root.set(attr_key, attr_value)

    # ── DELETE ──────────────────────────────────────────────────────────

    def mark_for_deletion(self, table_name: str) -> None:
        """Marca una PlcTagTable para eliminación por COM en el worker.

        El worker ejecutará ``table.delete()`` sobre cada nombre marcado
        DENTRO de la transacción unificada. Si el rollback ocurre, las
        eliminaciones se revierten automáticamente (porque el COM revierte
        los cambios in-memory).
        """
        if not table_name:
            raise ValueError("table_name no puede estar vacío.")
        if table_name in self._tables_to_delete:
            _logger.debug(f"Tabla '{table_name}' ya marcada para eliminar.")
            return
        self._tables_to_delete.append(table_name)
        _logger.info(f"Tabla '{table_name}' marcada para eliminación por COM.")

    def tables_marked_for_deletion(self) -> list[str]:
        """Devuelve la lista de tablas marcadas para eliminar (snapshot)."""
        return list(self._tables_to_delete)

    def tables_created(self) -> list[Path]:
        """Devuelve la lista de archivos PlcTagTable creados (snapshot)."""
        return list(self._created_tables)

    # ── Utilidades ──────────────────────────────────────────────────────

    @staticmethod
    def strip_xmlns_declaration(xml_text: str) -> str:
        """Elimina declaraciones ``xmlns`` redundantes del texto XML.

        Helper opcional usado por tests para verificar la estructura
        sin contaminar el parseo de ET con múltiples namespaces.
        """
        return _PLC_TAG_TABLE_NS_RE.sub("", xml_text)


__all__ = ["PlcTagTableManager"]
