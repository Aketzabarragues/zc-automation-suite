"""Parser SimaticML para extraer ``PlcUserConstant`` de un .xml exportado.

Recorre el árbol XML buscando los nodos ``SW.Tags.PlcUserConstant``
mediante la sintaxis de comodín ``{*}`` de Python 3.8+, que evita
hardcodear el namespace de Siemens.

Restricción arquitectónica: este parser es OFFLINE; no importa
``siemens_tia_scripting``. La única librería usada es
``xml.etree.ElementTree`` (stdlib).
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path


class SimaticMLTagParser:
    """Lee un .xml SimaticML y devuelve ``{valor_int: nombre_constante}``.

    Ignora entradas cuyo valor no sea casteable a ``int`` (constantes
    Real, String, Bool, etc.).
    """

    _CONSTANT_TAG = "{*}SW.Tags.PlcUserConstant"
    _NAME_TAG = "{*}Name"
    _VALUE_TAG = "{*}Value"

    @staticmethod
    def parse_user_constants(xml_file_path: str | Path) -> dict[str, str]:
        """Lee un .xml SimaticML y devuelve ``{valor_int: nombre_constante}``.

        Args:
            xml_file_path: Ruta al archivo .xml exportado por
                ``TIAProcessGateway.export_tag_table``.

        Returns:
            ``dict[str, str]`` con pares ``{valor_int_str: nombre}``.

        Raises:
            FileNotFoundError: Si el archivo no existe.
            ET.ParseError: Si el XML no es válido.
        """
        path = Path(xml_file_path)
        if not path.is_file():
            raise FileNotFoundError(
                f"No se encontró el archivo XML: '{path}'"
            )
        tree = ET.parse(str(path))
        root = tree.getroot()
        return SimaticMLTagParser._extract_constants(root)

    @classmethod
    def _extract_constants(cls, root: ET.Element) -> dict[str, str]:
        """Itera todos los nodos ``PlcUserConstant`` del árbol (recursivo)."""
        result: dict[str, str] = {}
        # ``ET.iter`` NO soporta el wildcard ``{*}`` (limitación Python 3.x).
        # Usamos ``findall(".//{*}...")`` que sí acepta la sintaxis wildcard.
        for constant in root.findall(f".//{cls._CONSTANT_TAG}"):
            name_el = constant.find(cls._NAME_TAG)
            value_el = constant.find(cls._VALUE_TAG)
            if name_el is None or value_el is None:
                continue
            name_text = (name_el.text or "").strip()
            value_text = (value_el.text or "").strip()
            if not name_text or not value_text:
                continue
            try:
                int_value = int(value_text)
            except ValueError:
                # Constantes Real / String / Bool: se descartan.
                continue
            result[str(int_value)] = name_text
        return result
