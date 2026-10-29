"""Regression test: ``ConfiguracionPanel.js`` debe leer
``excel_full.n_max`` y mostrar el nombre correcto de la tabla en el
empty state (``Tabla_Dimensiones``), no ``Tabla_Dispositivos``.

Tres bugs relacionados que viven juntos porque son el mismo malentendido
del nombre canonico de la tabla N_MAX:

  1. Empty state decia ``Tabla_Dispositivos`` (mensaje al operario).
     El nombre real de la tabla en el Excel corporativo es
     ``Tabla_Dimensiones`` (ver ``excel_parser_disp_dimensiones.py:N_MAX_TABLE_NAME``).
  2. El computed ``plcRows`` leia ``excel_full.dimensiones``, que NO
     existe en el shape del backend (``DataExcelCache.to_dict()`` solo
     emite ``excel_full.n_max``).
  3. El docstring del componente afirmaba el shape con la key
     ``excel_full.dimensiones``: tambien incorrecto.

Shape del backend (confirmado por ``DimensionesPLC.to_api_dict()``):
    ``excel_full.n_max`` es un dict ``{plc_name: {nmax_name: int}}``
    anidado. ``DataDimensionesPLC.to_api_dict`` ademas incluye
    ``N_MAX_ENTIDAD`` (siempre, incluso con valor 0).

Cobertura:
  - Empty state dice ``Tabla_Dimensiones``.
  - ``plcRows`` lee ``excel_full.n_max``, no ``excel_full.dimensiones``.
  - El docstring del header describe la shape correcta.

Nota: estos checks son ESTATICOS sobre el source. El comportamiento
runtime se valida con el smoke contra el Excel demo.
"""
from __future__ import annotations

import re
from pathlib import Path


COMPONENT_PATH = Path(
    r"D:\Zeus Control\Proyectos\GitHub\zc-automation-suite\areas\alimentacion\frontend\components\ConfiguracionPanel.js"
)


def _read_source() -> str:
    assert COMPONENT_PATH.exists(), (
        f"ConfiguracionPanel.js no encontrado en {COMPONENT_PATH}"
    )
    return COMPONENT_PATH.read_text(encoding="utf-8")


def test_no_dice_tabla_dispositivos() -> None:
    """El mensaje del empty state dice ``Tabla_Dimensiones``, no ``Tabla_Dispositivos``.

    El Excel corporativo usa ``Tabla_Dimensiones`` como nombre literal
    de la ``ListObject`` (ver ``N_MAX_TABLE_NAME`` en el parser). Si el
    componente dice ``Tabla_Dispositivos``, el operario busca esa tabla
    en su Excel, no la encuentra, y reporta bug fantasma.
    """
    src = _read_source()
    assert "Tabla_Dispositivos" not in src, (
        "ConfiguracionPanel.js aun menciona 'Tabla_Dispositivos'. "
        "El nombre real de la tabla N_MAX es 'Tabla_Dimensiones' "
        "(ver N_MAX_TABLE_NAME en excel_parser_disp_dimensiones.py)."
    )
    pattern = re.compile(r"Tabla_Dimensiones")
    assert pattern.search(src), (
        "Empty state debe mencionar 'Tabla_Dimensiones' (no la antigua "
        "'Tabla_Dispositivos')."
    )


def test_empty_state_dice_tabla_dimensiones() -> None:
    """El bloque ``v-else-if=!hasDimensiones`` usa el nombre correcto.

    Verifica que el span ``<span class="font-mono">`` del empty state
    diga ``Tabla_Dimensiones`` (mensaje al operario).
    """
    src = _read_source()
    pattern = re.compile(
        r'<span\s+class="font-mono">Tabla_Dimensiones</span>'
    )
    assert pattern.search(src), (
        "Empty state del panel Configuracion debe mostrar "
        "'<span class=\"font-mono\">Tabla_Dimensiones</span>' como "
        "mensaje al operario."
    )


def test_lee_n_max_no_dimensiones_en_computed() -> None:
    """``plcRows`` lee ``excelFull.value.n_max``, no ``excelFull.value.dimensiones``.

    El backend expone ``excel_full.n_max`` (``DataExcelCache.to_dict()``).
    El componente debe usar esa key. Si lee ``dimensiones``, el computed
    retorna ``undefined`` y siempre se pinta el empty state.
    """
    src = _read_source()
    bug_pattern = re.compile(
        r"excelFull\.value\s*&&\s*excelFull\.value\.dimensiones",
    )
    assert not bug_pattern.search(src), (
        "plcRows lee 'excelFull.value.dimensiones'. La key real "
        "del backend es 'n_max' (ver DataExcelCache.to_dict()). "
        "Cambiar a 'excelFull.value.n_max'."
    )
    pattern = re.compile(
        r"excelFull\.value\s*&&\s*excelFull\.value\.n_max",
    )
    assert pattern.search(src), (
        "plcRows debe leer 'excelFull.value.n_max' (shape del backend)."
    )


def test_docstring_no_referencia_dimensiones_como_key() -> None:
    """El docstring del header describe ``excel_full.n_max``, no ``excel_full.dimensiones``.

    Documentacion desactualizada confunde al siguiente developer.
    """
    src = _read_source()
    bug_pattern = re.compile(r"excel_full\.dimensiones\s*=")
    assert not bug_pattern.search(src), (
        "Docstring del componente describe shape con key "
        "'excel_full.dimensiones'. La key correcta es 'excel_full.n_max'."
    )
    pattern = re.compile(r"excel_full\.n_max\s*=")
    assert pattern.search(src), (
        "Docstring debe documentar shape con key 'excel_full.n_max'."
    )


def test_template_no_referencia_tabla_dispositivos() -> None:
    """El bloque template no contiene ``Tabla_Dispositivos`` en ningun sitio.

    Cobertura adicional: protege contra una reintroduccion del bug
    en el template (no solo en el docstring o en el mensaje).
    """
    src = _read_source()
    # Aislar el rango del template (mismo patron que test_template_baktilts.py).
    m_start = re.search(r"template:\s*/\*\s*html\s*\*/\s*`", src)
    m_end = re.search(r"`,\s*\};\s*$", src)
    assert m_start and m_end, "Template string no encontrado."
    template = src[m_start.end():m_end.start()]
    assert "Tabla_Dispositivos" not in template, (
        "El bloque template de ConfiguracionPanel.js contiene "
        "'Tabla_Dispositivos'. Debe ser 'Tabla_Dimensiones'."
    )