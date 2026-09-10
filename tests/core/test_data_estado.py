"""Tests del Data Block ``core.data.data_estado.DataEstado``.

Fase 3, paso 3.1.1.  Cubren:
  - Valores por defecto (worker muerto, TIA idle, sin proyecto).
  - Mutabilidad: los campos son asignables (dataclass no-frozen).
  - ``to_dict()`` produce un dict con la shape correcta, incluyendo
    el campo ``state`` por back-compat con la SPA actual.
  - El campo ``plcs`` se serializa como copia (no alias del list
    interno), para evitar que mutaciones externas filtren al DB.
"""
from __future__ import annotations

from core.data.data_estado import DataEstado


def test_data_estado_defaults() -> None:
    """Valores por defecto: worker muerto, TIA idle, sin proyecto."""
    estado = DataEstado()
    assert estado.worker_alive is False
    assert estado.tia_state == "idle"
    assert estado.project_name is None
    assert estado.project_path is None
    assert estado.plcs == []
    assert estado.last_error is None
    assert estado.last_ping_ok_unix is None


def test_data_estado_is_mutable() -> None:
    """Los campos son asignables (dataclass no-frozen)."""
    estado = DataEstado()
    estado.worker_alive = True
    estado.tia_state = "connected"
    estado.project_name = "MiProyecto"
    estado.project_path = "C:/TIA/MiProyecto.ap16"
    estado.plcs = ["S7-1500", "ET200"]
    estado.last_error = "ninguno"
    estado.last_ping_ok_unix = 1700000000.0

    assert estado.worker_alive is True
    assert estado.tia_state == "connected"
    assert estado.project_name == "MiProyecto"
    assert estado.project_path == "C:/TIA/MiProyecto.ap16"
    assert estado.plcs == ["S7-1500", "ET200"]
    assert estado.last_error == "ninguno"
    assert estado.last_ping_ok_unix == 1700000000.0


def test_data_estado_to_dict_shape() -> None:
    """``to_dict()`` produce la shape correcta, con ``state`` para
    back-compat con la SPA actual."""
    estado = DataEstado(
        worker_alive=True,
        tia_state="connected",
        project_name="MiProyecto",
        project_path="C:/TIA/MiProyecto.ap16",
        plcs=["S7-1500", "ET200"],
        last_error=None,
        last_ping_ok_unix=1700000000.0,
    )
    d = estado.to_dict()
    assert d == {
        "state": "connected",  # back-compat
        "worker_alive": True,
        "project_name": "MiProyecto",
        "project_path": "C:/TIA/MiProyecto.ap16",
        "plcs": ["S7-1500", "ET200"],
        "last_error": None,
        "last_ping_ok_unix": 1700000000.0,
    }


def test_data_estado_to_dict_copia_lista_plcs() -> None:
    """``to_dict()`` retorna una COPIA de ``plcs`` (no alias del list
    interno), para evitar que mutaciones externas filtren al DB."""
    estado = DataEstado(plcs=["PLC-1"])
    d = estado.to_dict()
    d["plcs"].append("PLC-2")  # mutar el dict NO debe afectar al DB
    assert estado.plcs == ["PLC-1"]
    # Y al revés: mutar el DB NO debe afectar a un dict ya emitido
    estado.plcs.append("PLC-3")
    d2 = estado.to_dict()
    assert d2["plcs"] == ["PLC-1", "PLC-3"]


def test_data_estado_plcs_default_factory_independiente() -> None:
    """Dos instancias no comparten el list de PLCs (default_factory)."""
    e1 = DataEstado()
    e2 = DataEstado()
    e1.plcs.append("PLC-compartido")
    assert e2.plcs == []  # la otra instancia NO se ve afectada
