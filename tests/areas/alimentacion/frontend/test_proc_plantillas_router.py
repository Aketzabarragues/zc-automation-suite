"""Tests del router Flask ``proc_plantillas_router``.

Cubre el endpoint ``GET /api/v1/procesos/plantillas``:

  - ``test_listar_plantillas_path_vacio``:
    ``get_plantillas_path()`` retorna ``""`` -> 200 con lista vacia
    y ``warning`` explicando que no esta configurado.
  - ``test_listar_plantillas_path_invalido``:
    ``get_plantillas_path()`` apunta a un dir inexistente -> 200 con
    lista vacia y ``warning``.
  - ``test_listar_plantillas_ok``:
    Hay subcarpetas con ``manifest.json`` valido -> 200 con la lista
    poblada y los campos canoonicos (``carpeta``, ``base``, ``codigo``,
    ``nombre``, ``minimos``).

El test del endpoint ``PUT`` (escritura + recarga del ConfigManager)
NO se incluye: la escritura a ``config.json`` es delicada y ya esta
cubierta indirectamente por la logica del backend en smoke tests.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from flask import Flask


# ── Helpers ──────────────────────────────────────────────────────────


def _make_app(config_manager: MagicMock | None = None) -> Flask:
    """Crea una app Flask minima con el ``ConfigManager`` mockeado.

    El router lee ``current_app.config["CONFIG_MANAGER"]``; basta con
    inyectarlo en ``app.config`` antes de registrar el blueprint.
    """
    app = Flask(__name__)
    app.config["TESTING"] = True
    if config_manager is not None:
        app.config["CONFIG_MANAGER"] = config_manager
    return app


@pytest.fixture
def plantillas_dir(tmp_path: Path) -> Path:
    """Crea un directorio con 2 subcarpetas (A, B) y ``manifest.json``
    canonico en cada una.
    """
    for code, base in [("A", 50010), ("B", 60010)]:
        sub = tmp_path / f"Plantilla_{code}"
        sub.mkdir()
        (sub / "manifest.json").write_text(
            json.dumps({
                "base": base,
                "codigo": code,
                "nombre": f"Test_{code}",
                "minimos": {
                    "N_MAX_PREAL": 3 if code == "A" else 5,
                    "N_MAX_PINT": 15 if code == "A" else 20,
                    "N_MAX_ALM": 16 if code == "A" else 24,
                    "N_MAX_ALM_HMI": 3 if code == "A" else 4,
                },
            }),
            encoding="utf-8",
        )
    # Subcarpeta sin manifest -> NO debe aparecer en la lista.
    (tmp_path / "Plantilla_C_sin_manifest").mkdir()
    return tmp_path


# ── Tests ────────────────────────────────────────────────────────────


def test_listar_plantillas_path_vacio() -> None:
    """``plantillas_path == ""`` -> 200 con lista vacia + warning."""
    from areas.alimentacion.frontend.proc_plantillas_router import bp

    config = MagicMock()
    config.get_plantillas_path.return_value = ""
    app = _make_app(config)
    app.register_blueprint(bp)
    client = app.test_client()

    resp = client.get("/api/v1/procesos/plantillas")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["plantillas"] == []
    assert "warning" in data
    assert "plantillas_path" in data["warning"].lower()


def test_listar_plantillas_path_invalido() -> None:
    """``plantillas_path`` apunta a un dir inexistente -> 200 con
    lista vacia + warning."""
    from areas.alimentacion.frontend.proc_plantillas_router import bp

    config = MagicMock()
    config.get_plantillas_path.return_value = "Z:/no/existe/aqui"
    app = _make_app(config)
    app.register_blueprint(bp)
    client = app.test_client()

    resp = client.get("/api/v1/procesos/plantillas")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["plantillas"] == []
    assert "warning" in data
    assert "Directorio no existe" in data["warning"]


def test_listar_plantillas_ok(plantillas_dir: Path) -> None:
    """Lista subcarpetas con ``manifest.json`` valido."""
    from areas.alimentacion.frontend.proc_plantillas_router import bp

    config = MagicMock()
    config.get_plantillas_path.return_value = str(plantillas_dir)
    app = _make_app(config)
    app.register_blueprint(bp)
    client = app.test_client()

    resp = client.get("/api/v1/procesos/plantillas")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    # 2 subcarpetas con manifest (la 3ª sin manifest se ignora).
    assert len(data["plantillas"]) == 2

    codigos = {p["codigo"] for p in data["plantillas"]}
    assert codigos == {"A", "B"}

    # Cada plantilla expone los campos canonicos del manifest.
    for p in data["plantillas"]:
        assert "carpeta" in p
        assert "base" in p
        assert "codigo" in p
        assert "nombre" in p
        assert "minimos" in p
        # El ``minimos`` viene tal cual del manifest (dict con las
        # 4 claves canonicas).
        for key in ("N_MAX_PREAL", "N_MAX_PINT", "N_MAX_ALM", "N_MAX_ALM_HMI"):
            assert key in p["minimos"]
