"""Guard de los defaults de configuración del área de alimentación.

Los defaults del área y el ``config.json`` que se instala por defecto
tienen que usar los MISMOS nombres de tabla y de carpetas TIA: un
nombre distinto (p. ej. ``000_Config_Dispositivos``) no existe en el
PLC, y el sync buscaria una tabla que no esta.
"""
from __future__ import annotations

import json
from pathlib import Path

from areas.alimentacion.helpers.config.config_defaults import install

REPO_ROOT = Path(__file__).resolve().parents[5]


def _config_instalado() -> dict:
    datos = json.loads(
        (REPO_ROOT / "config" / "config.json").read_text(encoding="utf-8-sig")
    )
    return datos["departments"]["alimentacion"]


def test_los_defaults_del_area_coinciden_con_el_config_instalado():
    """Los defaults del area no pueden divergir del config empaquetado."""
    alim = _config_instalado()
    vacio: dict = {}
    install(vacio, "alimentacion")

    assert vacio["global_config_table_name"] == alim["global_config_table_name"]
    for clave in ("proceso", "dispositivos", "nmax"):
        assert vacio["tia_folders"][clave] == alim["tia_folders"][clave], (
            f"La carpeta TIA '{clave}' del default del area no es la del "
            f"config instalado: el sync buscaria una tabla que no existe."
        )


def test_el_default_de_la_tabla_global_no_usa_el_nombre_legacy():
    """El nombre por defecto es el que existe en el PLC."""
    vacio: dict = {}
    install(vacio, "alimentacion")
    assert vacio["global_config_table_name"] == "0_Config_Dispositivos"


def test_install_no_pisa_lo_que_el_operario_configuro():
    """Si la clave esta, el default no se aplica."""
    alim = _config_instalado()
    cfg = {
        "global_config_table_name": "MI_TABLA",
        "tia_folders": {"nmax": "MI_CARPETA"},
    }
    install(cfg, "alimentacion")

    assert cfg["global_config_table_name"] == "MI_TABLA"
    assert cfg["tia_folders"]["nmax"] == "MI_CARPETA"
    assert cfg["tia_folders"]["dispositivos"] == alim["tia_folders"]["dispositivos"]
