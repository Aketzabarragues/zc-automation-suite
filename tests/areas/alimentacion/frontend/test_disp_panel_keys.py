"""Regression test: ``DispositivosPanel.js`` no debe keyear
``excel_full.dispositivos`` por ``canonical``.

El backend ``excel_loader.py`` produce ``dispositivos: {hw_type: tuple}``
con keys lowercase (``ed``, ``ea``, ``sa``, ...). El catalog del frontend
``(/api/v1/catalog``) emite cada tab como ``{hw_type, canonical, label}``
donde ``hw_type="ed"`` y ``canonical="DispED"``.

El componente debe exponer ``hwType`` en cada tab y usarlo para indexar
``ms.dispositivos``; usar ``canonical`` (``DispED``) rompe el lookup y la
SPA pinta "no contiene dispositivos" en TODAS las tabs aunque el cache
este lleno (bug visto en smoke en vivo).

Cobertura:
  - El computed ``tabs`` expone ``hwType`` mapeado a ``hw_type``.
  - ``activeDevices`` no accede ``ms.dispositivos[activeSubTab.value]``
    directamente (eso seria el bug); usa una indireccion via
    ``hwTypeByKey`` (o equivalente).
  - ``deviceCountsByTab`` tampoco itera ``Object.entries(disp)`` con
    keys canonical.

Nota: estos checks son ESTATICOS sobre el source. El comportamiento
runtime se valida en el smoke ``.build_cache/smoke/verify_disp_panel_fix.py``.
"""
from __future__ import annotations

import re
from pathlib import Path


COMPONENT_PATH = Path(
    r"D:\Zeus Control\Proyectos\GitHub\zc-automation-suite\areas\alimentacion\frontend\components\DispositivosPanel.js"
)


def _read_source() -> str:
    assert COMPONENT_PATH.exists(), (
        f"DispositivosPanel.js no encontrado en {COMPONENT_PATH}"
    )
    return COMPONENT_PATH.read_text(encoding="utf-8")


def test_tabs_computed_incluye_hwType_de_t_hw_type() -> None:
    """El computed ``tabs`` mapea ``t.hw_type`` a ``hwType``.

    Sin esta clave, el componente solo tendria ``key=canonical`` y
    caeria en el bug.
    """
    src = _read_source()
    pattern = re.compile(
        r"device_tabs\.map\(\(?t\)?\s*=>\s*\(\s*\{[^}]*hwType:\s*t\.hw_type",
        re.DOTALL,
    )
    assert pattern.search(src), (
        "tabs computed debe mapear hwType: t.hw_type. "
        "Sin esto, activeDevices no podra traducir canonical -> hw_type."
    )


def test_activeDevices_no_indexa_por_activeSubTab_directamente() -> None:
    """``activeDevices`` debe traducir activeSubTab (canonical) via
    un mapeo ``hwTypeByKey`` antes de acceder a ``ms.dispositivos``.

    El patron buggy es:
        ms.dispositivos[activeSubTab.value]
    porque ``activeSubTab.value == "DispED"`` y ``ms.dispositivos``
    solo tiene ``"ed"``.
    """
    src = _read_source()
    bug_pattern = re.compile(
        r"ms\.dispositivos\[\s*activeSubTab\.value\s*\]",
    )
    assert not bug_pattern.search(src), (
        "activeDevices accede ms.dispositivos[activeSubTab.value] "
        "directamente. Eso es el bug: el backend keyed "
        "por hw_type (lowercase), no canonical. Usar "
        "hwTypeByKey[activeSubTab.value] (mapping canonical -> hw_type)."
    )


def test_existe_mapeo_canonical_a_hw_type() -> None:
    """Hay un mapping ``key (canonical) -> hwType`` en algun computed.

    Forma esperada: ``hwTypeByKey`` (computed que itera tabs).
    """
    src = _read_source()
    pattern = re.compile(
        r"hwTypeByKey\s*=\s*computed\(\(\)\s*=>\s*\{[\s\S]*?m\[t\.key\]\s*=\s*t\.hwType",
    )
    assert pattern.search(src), (
        "Debe existir un computed hwTypeByKey que mapee canonical "
        "(t.key) -> hw_type (t.hwType). Sin esto, no se puede "
        "traducir activeSubTab a la key real de ms.dispositivos."
    )


def test_activeDevices_usa_hwTypeByKey() -> None:
    """``activeDevices`` consulta ``hwTypeByKey[activeSubTab.value]``
    (o equivalente con lookup indirecto) antes de indexar.
    """
    src = _read_source()
    pattern = re.compile(
        r"const\s+hw\s*=\s*hwTypeByKey\.value\[activeSubTab\.value\]",
    )
    assert pattern.search(src), (
        "activeDevices debe hacer `hw = hwTypeByKey.value[activeSubTab.value]` "
        "y luego `ms.dispositivos[hw]`. Sin esto, el componente "
        "indexa por canonical y falla."
    )


def test_deviceCountsByTab_no_itera_keys_canonical() -> None:
    """``deviceCountsByTab`` itera sobre ``tabs.value`` (canonical) y
    consulta el backend con ``t.hwType``. NO debe iterar
    ``Object.entries(disp)`` directamente porque las keys son hw_type.
    """
    src = _read_source()
    bug_pattern = re.compile(
        r"for\s*\(\s*const\s*\[\s*key\s*,\s*lst\s*\]\s*of\s*Object\.entries\(\s*disp\s*\)\)",
    )
    assert not bug_pattern.search(src), (
        "deviceCountsByTab itera Object.entries(disp) y guarda "
        "out[key] con la key hw_type. El template indexa con "
        "deviceCountsByTab[t.key] (canonical). Resultado: siempre 0. "
        "Iterar sobre tabs.value y leer disp[t.hwType]."
    )