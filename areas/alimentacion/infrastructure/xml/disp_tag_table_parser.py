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
    """Lee un .xml SimaticML y devuelve ``{nombre_constante: valor_int}``.

    **Usa el nombre como clave** (no el valor) para evitar colisiones:
    si dos PlcUserConstant tienen el mismo valor entero (p.ej. dos
    N_MAX con value=25), la versión anterior basada en ``{valor:
    nombre}`` perdería una entrada al iterar el dict. Aquí el nombre
    es el identificador estable y siempre único dentro de la tabla.

    Ignora entradas cuyo valor no sea casteable a ``int`` (constantes
    Real, String, Bool, etc.).
    """

    _CONSTANT_TAG = "{*}SW.Tags.PlcUserConstant"
    _NAME_TAG = "{*}Name"
    _VALUE_TAG = "{*}Value"

    @staticmethod
    def parse_user_constants(xml_file_path: str | Path) -> dict[str, int]:
        """Lee un .xml SimaticML y devuelve ``{nombre: valor_int}``.

        Args:
            xml_file_path: Ruta al archivo .xml exportado por
                ``TIAProcessGateway.export_tag_table``.

        Returns:
            ``dict[str, int]`` con pares ``{nombre: valor}``. El valor
            es SIEMPRE un entero (las constantes no enteras se
            descartan).

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
    def _extract_constants(cls, root: ET.Element) -> dict[str, int]:
        """Itera todos los nodos ``PlcUserConstant`` del árbol (recursivo).

        Retorna ``{nombre: valor_int}``. Si dos PlcUserConstant tienen
        el mismo nombre (no debería pasar en TIA, pero por si acaso),
        gana la última ocurrencia.
        """
        result: dict[str, int] = {}
        # ``ET.iter`` NO soporta el wildcard ``{*}`` (limitación Python 3.x).
        # Usamos ``findall(".//{*}...")`` que sí acepta la sintaxis wildcard.
        for constant in root.findall(f".//{cls._CONSTANT_TAG}"):
            # FIX: usar ``.//`` (recursivo) porque ``<Name>`` y ``<Value>``
            # están dentro de ``<AttributeList>``, NO como hijos directos
            # de ``<PlcUserConstant>``. Esto es coherente con el fix
            # análogo en ``TagTableModifier.read_user_constants_with_uids``
            # (ver ``infrastructure/xml/disp_tag_table_modifier.py``).
            name_el = constant.find(f".//{cls._NAME_TAG}")
            value_el = constant.find(f".//{cls._VALUE_TAG}")
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
            result[name_text] = int_value
        return result
