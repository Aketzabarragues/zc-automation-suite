"""Inyector offline de valores ``<Value>`` en PlcTagTable (SimaticML).

Replica moderna del ``TablaVariablesInjector`` legacy. En lugar de regex
frágil sobre texto plano, usa ``xml.etree.ElementTree`` con la sintaxis
de comodín ``{*}`` (inmune a cambios de versión del esquema SimaticML).

Restricción arquitectónica: este módulo es OFFLINE; no importa
``siemens_tia_scripting``. Solo usa la stdlib (``pathlib`` y ``xml.etree``).

Caso de uso principal
---------------------
TIA Portal Openness tiene un bug de "Histéresis de Compilación": si las
constantes N_MAX cambian DESPUÉS de importar la tabla, la compilación no
recalcula las dimensiones de los DBs. Solución: inyectar los valores
N_MAX del Excel directamente en el archivo XML físico ANTES de importar.

Estrategia (puramente ET, consistente con el resto del repo):
  - Recorre ``.build/`` buscando archivos PlcTagTable.xml.
  - Para cada constante esperada (``{nombre: valor}``), busca el nodo
    ``{*}SW.Tags.PlcUserConstant`` cuyo ``{*}Name`` coincida.
  - Sustituye SOLO el inner text de ``{*}Value`` por el valor del Excel.
  - NO toca ``{*}Name``, ``{*}ID``, ``{*}Handle``, ``{*}SystemId``, etc.

Idempotencia
------------
Aplicar dos veces con los mismos parámetros produce el mismo resultado
(la segunda vez, el valor ya coincide y no hay cambios que aplicar).
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, cast


_logger: logging.Logger = logging.getLogger(f"{__name__}.TagTableValueInjector")


_PLC_USER_CONSTANT = "{*}SW.Tags.PlcUserConstant"
_NAME_TAG = "{*}Name"
_VALUE_TAG = "{*}Value"


def _get_text(elem: ET.Element | None) -> str:
    """Devuelve ``elem.text`` stripped o ``""`` si elem es None / sin texto."""
    if elem is None:
        return ""
    return (elem.text or "").strip()


class TagTableValueInjector:
    """Editor offline que sobreescribe ``<Value>`` de PlcUserConstant.

    Diseñado para resolver el bug de Histéresis de Compilación de TIA
    Portal: las constantes N_MAX se inyectan ANTES de importar la tabla
    para que la primera compilación ya respete las nuevas dimensiones.
    """

    @classmethod
    def inject_into_build(
        cls,
        ruta_build: str | Path,
        constants: dict[str, int],
    ) -> bool:
        """Inyecta los valores N_MAX del Excel en el archivo PlcTagTable.

        Args:
            ruta_build: ruta al directorio ``.build/`` o al archivo XML
                PlcTagTable concreto. Si es un directorio, busca el
                primer archivo ``*PlcTagTable*.xml``.
            constants: ``{nombre_constante: valor}`` (ej.
                ``{"1620_N_MAX_PREAL": 25, ...}``).

        Returns:
            ``True`` si al menos una constante fue modificada.
            ``False`` si no se encontró ninguna (warning loggeado).
        """
        build_path = Path(ruta_build)
        if not build_path.exists():
            _logger.error(f"Ruta build no existe: {ruta_build}")
            return False

        tabla_path = cls._locate_tag_table_xml(build_path)
        if tabla_path is None:
            _logger.warning(
                f"No se encontró archivo PlcTagTable en {ruta_build}."
            )
            return False

        _logger.info(f"Inyectando N_MAX en tabla de variables: {tabla_path.name}")
        return cls._inject_into_file(tabla_path, constants)

    @classmethod
    def inject_into_file(
        cls,
        xml_path: str | Path,
        constants: dict[str, int],
    ) -> bool:
        """Inyecta los valores directamente en un archivo PlcTagTable.

        API expuesta para casos donde el caller ya conoce la ruta del XML
        (no necesita búsqueda).

        Args:
            xml_path: ruta absoluta al archivo PlcTagTable.xml.
            constants: ``{nombre_constante: valor}``.

        Returns:
            ``True`` si al menos una constante fue modificada.
        """
        path = Path(xml_path)
        if not path.is_file():
            raise FileNotFoundError(f"No se encontró el archivo: '{path}'")
        return cls._inject_into_file(path, constants)

    # ── Internos ────────────────────────────────────────────────────────

    @classmethod
    def _locate_tag_table_xml(cls, path: Path) -> Path | None:
        """Localiza un PlcTagTable.xml dentro de ``path`` (dir o archivo).

        Estrategia:
          - Si ``path`` es un archivo, lo retorna directamente.
          - Si es directorio, hace ``rglob("*.xml")`` y filtra los
            archivos cuyo contenido incluya el token ``PlcTagTable``.
            Toma el más reciente por ``mtime`` (por si hay varios).
        """
        if path.is_file():
            return path
        if not path.is_dir():
            return None

        candidatos = list(path.rglob("*.xml"))
        candidatos_con_tablas: list[Path] = []
        for p in candidatos:
            try:
                contenido = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if "PlcTagTable" in contenido:
                candidatos_con_tablas.append(p)

        if not candidatos_con_tablas:
            return None
        # El más reciente (por si hay varios).
        candidatos_con_tablas.sort(key=lambda f: f.stat().st_mtime, reverse=True)
        return candidatos_con_tablas[0]

    @classmethod
    def _inject_into_file(cls, xml_path: Path, constants: dict[str, int]) -> bool:
        """Modifica el árbol XML en memoria y persiste si hubo cambios."""
        # ``ET.parse`` está tipado como ``ElementTree[Element | None]`` por
        # invariancia de generics; en la práctica nunca devuelve None con
        # un archivo XML válido. Usamos Any para silenciar el warning sin
        # perder el tipado fuerte del ``_root``.
        tree: Any = ET.parse(str(xml_path))
        root: ET.Element = cast(ET.Element, tree.getroot())
        if root is None:
            _logger.error(f"XML sin root: '{xml_path}'")
            return False

        cambios = 0
        # Indexamos las PlcUserConstant por nombre para búsqueda O(1).
        constants_by_name: dict[str, ET.Element] = {}
        for constant in root.findall(f".//{_PLC_USER_CONSTANT}"):
            name_el = constant.find(_NAME_TAG)
            name_text = _get_text(name_el)
            if name_text:
                constants_by_name[name_text] = constant

        for constant_name, new_value in constants.items():
            constant = constants_by_name.get(constant_name)
            if constant is None:
                _logger.warning(
                    f"  - {constant_name} no encontrada en la tabla (se omite)"
                )
                continue
            value_el = constant.find(_VALUE_TAG)
            if value_el is None:
                _logger.warning(
                    f"  - {constant_name} sin nodo <Value> (se omite)"
                )
                continue
            value_text = _get_text(value_el)
            new_value_str = str(int(new_value))
            if value_text == new_value_str:
                continue  # idempotente: ya estaba así
            value_el.text = new_value_str
            cambios += 1
            _logger.debug(f"  - {constant_name}: {value_text} -> {new_value_str}")

        if cambios == 0:
            _logger.info(
                f"Ningún valor modificado en {xml_path.name} (idempotente o sin match)."
            )
            return False

        tree.write(str(xml_path), encoding="utf-8", xml_declaration=True)
        _logger.info(f"✅ {cambios} StartValue(s) actualizados en {xml_path.name}.")
        return True


__all__ = ["TagTableValueInjector"]
