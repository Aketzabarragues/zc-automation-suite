"""Icono de bandeja y menú del operario.

Menú (click derecho):
  - Iniciar/Parar web   ← toggle según estado
  - Abrir panel web     ← enable si web.is_alive()
  - Estado              ← balloon tip con info del supervisor
  - Salir               ← para web + cierra icono

Icon.run() bloquea el main thread (pystray lo requiere así).
El supervisor vive en hilos daemon separados.
"""
from __future__ import annotations

import logging
import time
import webbrowser
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw, ImageFont

APP_NAME = "ZC Automation Suite"


def _load_icon_image(icon_path: Path | None, log: logging.Logger) -> Image.Image:
    """Carga el .ico o genera un placeholder RGBA en memoria."""
    if icon_path and icon_path.is_file():
        try:
            return Image.open(icon_path)
        except Exception as exc:  # noqa: BLE001
            log.warning("No se pudo cargar %s (%s); usando placeholder.", icon_path, exc)

    # Placeholder 64x64 RGBA. Misma paleta y logica de centrado que
    # make_icon.py::_make_placeholder_icon (incluido el nudge vertical
    # de -4 px) para que el icono del tray sin .ico en disco sea
    # consistente con el .ico generado para el build. Fondo cuadrado
    # (no rounded) porque a 64 px las esquinas redondeadas quedan
    # pixeladas.
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, size, size), fill=(15, 76, 117, 255))

    text = "ZC"
    try:
        font = ImageFont.truetype("seguisb.ttf", 28)
    except OSError:
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(
        ((size - tw) / 2 - bbox[0], (size - th) / 2 - bbox[1] - 4),
        text,
        fill=(255, 255, 255, 255),
        font=font,
    )
    return img


def build_status_text(web) -> str:
    """Cadena multi-línea para el balloon tip."""
    web_state = "OK" if web.is_alive() else "DOWN"
    return (
        f"Web: {web_state}\n"
        f"  http://{web.host}:{web.port}\n"
        f"  Restarts: {web.restart_count}\n"
    )


def _make_text(getter: Callable[[], str]) -> Callable[[object], str]:
    """Envuelve un callable para que pystray lo evalúe en cada render."""
    return lambda _item: getter()


def _make_enabled(getter: Callable[[], bool]) -> Callable[[object], bool]:
    """Igual para el flag enabled."""
    return lambda _item: getter()


def _refresh_menu(icon_obj) -> None:
    """Re-renderiza el menú (necesario tras cambios de estado)."""
    if icon_obj is not None:
        try:
            icon_obj.update_menu()
        except Exception:  # noqa: BLE001
            pass


def run_tray(
    web,
    icon_path: Path | None,
    log: logging.Logger,
    on_before_exit: Callable[[], None] | None = None,
) -> None:
    """Muestra el icono de bandeja. Bloquea hasta 'Salir'.

    Args:
        web: ``MainServiceSupervisor`` (start/stop del web + main loop).
        icon_path: Ruta al .ico (None = placeholder en memoria).
        log: Logger del launcher.
        on_before_exit: Hook opcional invocado ANTES de detener el icono.
            Pensado para que ``main.py`` cierre recursos limpios sin
            que el módulo de bandeja tenga que conocerlos.
    """
    from pystray import Icon, Menu, MenuItem

    icon_img = _load_icon_image(icon_path, log)
    icon_ref: dict[str, object] = {"icon": None}

    def on_toggle_web(_icon, _item) -> None:
        if web.is_alive():
            log.info("Menu -> Parar web")
            web.stop(timeout=5.0)
        else:
            log.info("Menu -> Iniciar web")
            web.start()
            # Da tiempo al Flask daemon a bindear.
            deadline = time.time() + 10.0
            while time.time() < deadline and not web.is_alive():
                time.sleep(0.2)
        log.info("Web alive=%s", web.is_alive())
        _refresh_menu(icon_ref["icon"])

    def on_open_web(_icon, _item) -> None:
        if not web.is_alive():
            log.warning("Menu -> Abrir panel web: web no esta corriendo.")
            return
        url = f"http://{web.host}:{web.port}"
        log.info("Menu -> Abrir panel web (%s)", url)
        webbrowser.open(url)

    def on_status(icon_obj, _item) -> None:
        status = build_status_text(web)
        log.info("Menu -> Estado solicitado:\n%s", status)
        try:
            icon_obj.notify(APP_NAME, status)
        except Exception as exc:  # noqa: BLE001
            log.warning("Icon.notify() no disponible: %s", exc)

    def on_exit(icon_obj, _item) -> None:
        log.info("Menu -> Salir solicitado por el operario.")
        if on_before_exit is not None:
            try:
                on_before_exit()
            except Exception as exc:  # noqa: BLE001
                # El hook no debe bloquear la salida del icono.
                log.error("on_before_exit lanzo excepcion; continuando con stop: %s", exc)
        icon_obj.stop()

    def web_text() -> str:
        return "Parar web" if web.is_alive() else "Iniciar web"

    def abrir_web_enabled() -> bool:
        return web.is_alive()

    menu = Menu(
        MenuItem(_make_text(web_text), on_toggle_web),
        Menu.SEPARATOR,
        MenuItem("Abrir panel web", on_open_web, enabled=_make_enabled(abrir_web_enabled), default=True),
        MenuItem("Estado", on_status),
        Menu.SEPARATOR,
        MenuItem("Salir", on_exit),
    )

    icon = Icon(
        name="zc_automation_suite",
        icon=icon_img,
        title=APP_NAME,
        menu=menu,
    )
    icon_ref["icon"] = icon
    log.info("Icono de bandeja mostrado. Click derecho -> menu.")
    icon.run()
    log.info("Bucle del icono de bandeja terminado.")


__all__ = ["run_tray", "build_status_text", "_make_text", "_make_enabled", "APP_NAME"]
