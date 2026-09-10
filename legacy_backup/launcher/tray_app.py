"""Icono de bandeja de sistema (system tray) y menú de operario.

Menú (click derecho), con enable/disable dinámico:

    [Iniciar web] / [Parar web]      ← uno u otro según estado
    ─────────
    [Abrir panel web]                 ← enable si web.is_alive()
    [Estado]                          ← siempre enable
    ─────────
    [Salir]                           ← siempre enable

Detalles de implementación:
  - pystray 0.19.x en Windows usa ``pystray._win32`` vía ``ctypes``.
    NO requiere pywin32 runtime más allá de las deps transitivas.
  - ``Icon.run()`` es BLOQUEANTE: vive en el main thread. El
    supervisor del web corre en un hilo daemon separado.
  - Para menú dinámico (enable/disable según estado), pystray 0.19.x
    acepta callables en los campos ``text``/``enabled``/``visible``
    de MenuItem. Tras cada cambio de estado se llama
    ``icon.update_menu()`` para re-renderizar.
  - En modo ``--noconsole`` (Fase 2) la bandeja SIGUE funcionando:
    pystray no necesita stdout.
  - Para "mostrar estado" sin GUI Tk/tkinter adicional, usamos
    ``Icon.notify()`` (balloon tip de Windows).
"""
from __future__ import annotations

import logging
import webbrowser
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from PIL import Image, ImageDraw, ImageFont

if TYPE_CHECKING:
    from launcher.web_supervisor import WebServiceSupervisor


APP_NAME = "ZC Automation Suite"


def _load_icon_image(icon_path: Path | None, log: logging.Logger) -> Image.Image:
    """Carga el icono del .ico o genera un placeholder en memoria."""
    if icon_path and icon_path.is_file():
        try:
            return Image.open(icon_path)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "No se pudo cargar %s (%s); usando placeholder.",
                icon_path,
                exc,
            )

    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, 64, 64), fill=(15, 76, 117, 255))
    try:
        font = ImageFont.truetype("seguisb.ttf", 28)
    except OSError:
        font = ImageFont.load_default()
    draw.text((12, 16), "ZC", fill=(255, 255, 255, 255), font=font)
    return img


def build_status_text(web: "WebServiceSupervisor") -> str:
    """Cadena multi-línea que verá el operario en el balloon tip."""
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


def run_tray(
    web: "WebServiceSupervisor",
    icon_path: Path | None,
    log: logging.Logger,
    on_before_exit: Callable[[], None] | None = None,
) -> None:
    """Ejecuta el icono de bandeja (bloqueante hasta 'Salir').

    Args:
        web: Supervisor del web server FastAPI/uvicorn.
        icon_path: Ruta al .ico (o ``None`` para usar placeholder).
        log: Logger del launcher.
        on_before_exit: Hook opcional invocado por ``on_exit`` ANTES de
            detener el icono de bandeja. Pensado para que el composition
            root (``main_tray.py``) cierre limpiamente sus recursos
            (e.g. parar el web server) sin que el módulo de la bandeja
            tenga que conocerlos. Si lanza, se loggea y se continúa
            (no debe bloquear la salida del icono).
    """
    from pystray import Icon, Menu, MenuItem

    icon_img = _load_icon_image(icon_path, log)
    icon_ref: dict[str, "Icon | None"] = {"icon": None}

    def refresh() -> None:
        ic = icon_ref["icon"]
        if ic is not None:
            try:
                ic.update_menu()
            except Exception:  # noqa: BLE001
                pass

    def on_toggle_web(_icon, _item) -> None:
        if web.is_alive():
            log.info("Menu -> Parar web")
            web.stop(timeout=5.0)
        else:
            log.info("Menu -> Iniciar web")
            web.start()
            # Da tiempo a uvicorn a bindear.
            import time

            deadline = time.time() + 10.0
            while time.time() < deadline and not web.is_alive():
                time.sleep(0.2)
        log.info("Web alive=%s", web.is_alive())
        refresh()

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
                # Loggeamos y continuamos con el stop del pystray.
                log.error(
                    "on_before_exit lanzo excepcion; continuando con stop: %s",
                    exc,
                )
        icon_obj.stop()

    def web_text() -> str:
        return "Parar web" if web.is_alive() else "Iniciar web"

    def abrir_web_enabled() -> bool:
        return web.is_alive()

    menu = Menu(
        MenuItem(_make_text(web_text), on_toggle_web),
        Menu.SEPARATOR,
        MenuItem(
            "Abrir panel web",
            on_open_web,
            enabled=_make_enabled(abrir_web_enabled),
            default=True,
        ),
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


__all__ = ["run_tray", "build_status_text", "APP_NAME"]
