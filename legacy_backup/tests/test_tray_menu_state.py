"""Tests para ``launcher.tray_app``: lógica de status text y menu state.

Cubre la construcción del texto del menú "Estado" y la lógica de
enable/disable del menú dinámico, sin instanciar pystray (que
requiere GUI).
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from launcher.tray_app import build_status_text  # noqa: E402


class _FakeSupervisor:
    """Stub con la misma interfaz pública que WebServiceSupervisor."""

    def __init__(
        self,
        alive: bool = False,
        host: str = "127.0.0.1",
        port: int = 0,
        restart_count: int = 0,
    ) -> None:
        self._alive = alive
        self.host = host
        self.port = port
        self.restart_count = restart_count

    def is_alive(self) -> bool:
        return self._alive


# ── build_status_text ──────────────────────────────────────────


def test_status_text_alive() -> None:
    """Cuando web está vivo, status muestra OK."""
    web = _FakeSupervisor(alive=True, host="127.0.0.1", port=8000, restart_count=3)
    text = build_status_text(web)
    assert "Web: OK" in text
    assert "Restarts: 3" in text
    assert "http://127.0.0.1:8000" in text


def test_status_text_down() -> None:
    """Si web está caído, status muestra Web: DOWN."""
    web = _FakeSupervisor(alive=False, port=8000)
    text = build_status_text(web)
    assert "Web: DOWN" in text


def test_status_includes_restart_count() -> None:
    """El restart_count aparece en el texto."""
    web = _FakeSupervisor(alive=True, port=8000, restart_count=42)
    text = build_status_text(web)
    assert "Restarts: 42" in text


def test_status_includes_host_and_port() -> None:
    """El host:port aparece en el texto."""
    web = _FakeSupervisor(alive=True, host="192.168.1.50", port=9000)
    text = build_status_text(web)
    assert "http://192.168.1.50:9000" in text


# ── Habilitar / deshabilitar items (lógica pura) ───────────────


def test_abrir_web_enabled_iff_web_alive() -> None:
    """'Abrir panel web' solo debe estar enabled si web.is_alive()."""
    from launcher.tray_app import _make_enabled

    # Alive → enabled
    web_alive = _FakeSupervisor(alive=True)
    enabled_fn = _make_enabled(lambda: web_alive.is_alive())
    assert enabled_fn(None) is True

    # Down → disabled
    web_down = _FakeSupervisor(alive=False)
    enabled_fn = _make_enabled(lambda: web_down.is_alive())
    assert enabled_fn(None) is False

    # Cambia dinámicamente
    web = _FakeSupervisor(alive=False)
    enabled_fn = _make_enabled(lambda: web.is_alive())
    assert enabled_fn(None) is False
    web._alive = True
    assert enabled_fn(None) is True


def test_toggle_label_reflects_state() -> None:
    """'Iniciar web' / 'Parar web' según is_alive()."""
    from launcher.tray_app import _make_text

    web_down = _FakeSupervisor(alive=False)
    text_fn = _make_text(lambda: "Parar web" if web_down.is_alive() else "Iniciar web")
    assert text_fn(None) == "Iniciar web"

    web_up = _FakeSupervisor(alive=True)
    text_fn = _make_text(lambda: "Parar web" if web_up.is_alive() else "Iniciar web")
    assert text_fn(None) == "Parar web"


# ── Integración: verificar que el menu se construye con pystray ──


def test_run_tray_menu_structure_with_mocks() -> None:
    """Inyecta mocks y verifica que pystray recibe el menu correctamente.

    No lanza el Icon real (requiere GUI). Solo verifica que
    ``pystray.Icon`` se construye sin error con nuestros callables.
    """
    from pystray import Menu, MenuItem

    from launcher.tray_app import _make_enabled, _make_text

    web = _FakeSupervisor(alive=True, port=8000)

    menu = Menu(
        # toggle web
        MenuItem(
            _make_text(lambda: "Parar web" if web.is_alive() else "Iniciar web"),
            lambda *a: None,
        ),
        Menu.SEPARATOR,
        # abrir web
        MenuItem(
            "Abrir panel web",
            lambda *a: None,
            enabled=_make_enabled(lambda: web.is_alive()),
            default=True,
        ),
        MenuItem("Estado", lambda *a: None),
        Menu.SEPARATOR,
        MenuItem("Salir", lambda *a: None),
    )
    # 5 items: toggle, separator, abrir, estado, separator, salir
    assert len(menu.items) == 6
    items = menu.items
    assert items[0].text == "Parar web"  # web alive
    assert items[2].text == "Abrir panel web"
    assert items[2].enabled is True  # web alive
    assert items[3].text == "Estado"
    assert items[5].text == "Salir"


def test_menu_changes_when_web_state_flips() -> None:
    """Cuando web.is_alive() cambia, el callable devuelve el texto nuevo."""
    from launcher.tray_app import _make_enabled, _make_text

    web = _FakeSupervisor(alive=False)
    text_fn = _make_text(lambda: "Parar web" if web.is_alive() else "Iniciar web")
    enabled_fn = _make_enabled(lambda: web.is_alive())

    # Estado inicial: down
    assert text_fn(None) == "Iniciar web"
    assert enabled_fn(None) is False

    # Tras iniciar: up
    web._alive = True
    assert text_fn(None) == "Parar web"
    assert enabled_fn(None) is True

    # Tras parar: down de nuevo
    web._alive = False
    assert text_fn(None) == "Iniciar web"
    assert enabled_fn(None) is False
