"""Tests de la bandeja: el menu y, sobre todo, la salida limpa."""

from __future__ import annotations

from typing import Any

from zc_suite.bandeja import Bandeja


class IconoFalso:
    """El icono de pystray, de mentira."""

    def __init__(self) -> None:
        self.parado = False
        self.notificaciones: list[tuple[str, str]] = []
        self.menu_actualizado = 0

    def stop(self) -> None:
        self.parado = True

    def notify(self, titulo: str, texto: str) -> None:
        self.notificaciones.append((titulo, texto))

    def update_menu(self) -> None:
        self.menu_actualizado += 1


class WebFalsa:
    """El servidor web, de mentira."""

    def __init__(self, viva: bool = True) -> None:
        self.viva = viva
        self.arranques = 0
        self.paradas = 0

    def is_alive(self) -> bool:
        return self.viva

    def start(self) -> None:
        self.arranques += 1
        self.viva = True

    def stop(self, timeout: float = 5.0) -> None:
        self.paradas += 1
        self.viva = False

    def wait_until_alive(self, timeout_s: float = 10.0) -> bool:
        return self.viva


def _caja(
    web: Any,
    parar_tia: Any,
    estado_tia: str = "desconectado",
) -> Bandeja:
    """Una bandeja con las dependencias ya puestas."""
    return Bandeja(
        url="http://127.0.0.1:9484",
        web=web,
        estado_tia=lambda: estado_tia,
        parar_tia=parar_tia,
    )


def test_salir_para_todo_y_cierra_el_icono() -> None:
    """Salir para la web, para TIA y hace ``icon.stop()``."""
    web = WebFalsa()
    paradas: list[bool] = []
    caja = _caja(web, lambda: paradas.append(True))
    icono = IconoFalso()

    caja.al_salir(icono, None)

    assert paradas == [True]
    assert web.paradas == 1
    assert icono.parado is True


def test_un_fallo_al_parar_no_impide_cerrar() -> None:
    """Si parar falla, el icono se cierra igual: el proceso tiene que salir."""
    web = WebFalsa()
    caja = _caja(web, _reventar)
    icono = IconoFalso()

    caja.al_salir(icono, None)

    assert icono.parado is True


def _reventar() -> None:
    raise RuntimeError("no se pudo parar")


def test_alternar_web_la_para_si_esta_viva() -> None:
    """Con la web viva, el item la para."""
    web = WebFalsa(viva=True)
    caja = _caja(web, lambda: None)

    caja.al_alternar_web(IconoFalso(), None)

    assert web.paradas == 1
    assert web.viva is False


def test_alternar_web_la_arranca_si_esta_parada() -> None:
    """Con la web parada, el item la arranca."""
    web = WebFalsa(viva=False)
    caja = _caja(web, lambda: None)

    caja.al_alternar_web(IconoFalso(), None)

    assert web.arranques == 1
    assert web.viva is True


def test_el_texto_del_item_cambia_con_el_estado() -> None:
    """El item dice "Iniciar web" o "Parar web" segun como este."""
    web = WebFalsa(viva=True)
    caja = _caja(web, lambda: None)

    assert caja.texto_del_menu_web() == "Parar web"

    web.viva = False
    assert caja.texto_del_menu_web() == "Iniciar web"


def test_abrir_el_panel_solo_si_la_web_esta_viva(monkeypatch: Any) -> None:
    """Con la web parada, no se abre el navegador."""
    web = WebFalsa(viva=False)
    caja = _caja(web, lambda: None)
    abiertos: list[str] = []
    monkeypatch.setattr("zc_suite.bandeja.webbrowser.open", lambda url: abiertos.append(url))

    caja.al_abrir_web(IconoFalso(), None)

    assert abiertos == []


def test_el_estado_dice_como_esta_la_web_y_tia() -> None:
    """El globo de estado dice las dos cosas."""
    web = WebFalsa(viva=True)
    caja = _caja(web, lambda: None, estado_tia="conectado (V21.0)")

    texto = caja.texto_del_estado()

    assert "Web: OK" in texto
    assert "http://127.0.0.1:9484" in texto
    assert "TIA: conectado (V21.0)" in texto


def test_el_estado_avisa_cuando_la_web_esta_caida() -> None:
    """Con la web caida, el globo lo dice."""
    web = WebFalsa(viva=False)
    caja = _caja(web, lambda: None)

    assert "Web: DOWN" in caja.texto_del_estado()


def test_el_estado_se_notifica_al_icono() -> None:
    """El item "Estado" manda el globo."""
    caja = _caja(WebFalsa(viva=True), lambda: None)
    icono = IconoFalso()

    caja.al_estado(icono, None)

    assert icono.notificaciones
    titulo, texto = icono.notificaciones[0]
    assert titulo == "ZC Automation Suite"
    assert "Web: OK" in texto
