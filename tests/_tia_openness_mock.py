"""Mock DRY de ``siemens_tia_scripting`` para los tests del worker OT.

El wrapper de Siemens solo esta disponible en una maquina con TIA Portal
instalado, asi que los tests del worker persistente y de los handlers
del ``COMMAND_REGISTRY`` necesitan sustituirlo por un mock. Antes de
este modulo, cada test redefinia su propio ``_build_fake_ts()`` inline
(typicamente ~15 lineas), con pequenas variaciones que no aportan
valor y duplican el riesgo de divergencia (e.g. un test olvida
exponer ``Enums.PortalMode.WithGraphicalUserInterface`` y luego otro
test lo asume).

Este modulo expone:

  - ``build_fake_ts(portal=None, *, attach_side_effect=None)``: el
    mock reutilizable. Crea un wrapper con:
        * ``Enums.PortalMode.AnyUserInterface``
        * ``Enums.PortalMode.WithGraphicalUserInterface``
        * ``Enums.PortalMode.WithoutGraphicalUserInterface``
        * ``attach_portal(...)`` (retorna ``portal`` o lanza
          ``attach_side_effect``)
        * ``__file__`` apuntando al exe bundleado cuando aplica (no
          usado por los tests; el atributo solo esta para evitar
          ``AttributeError`` en sitios defensivos del worker).

  - ``FakePortal`` (via ``MagicMock(name="FakePortal")`` por defecto):
    expone ``detach()``, ``get_process_id()`` (default 12345) y todo
    lo que un test pueda querer inspeccionar. Si el caller quiere un
    portal con un PID concreto, lo pasa en ``portal=`` o lo asigna
    despues.

Uso tipico en un test:

    from tests._tia_openness_mock import build_fake_ts

    def test_algo() -> None:
        ts = build_fake_ts()
        with patch("core.infrastructure.tia.worker_tia._load_siemens_wrapper",
                   return_value=ts):
            worker_tia.main_persistent_loop()

    def test_attach_falla() -> None:
        ts = build_fake_ts(attach_side_effect=RuntimeError("boom"))
        # ...

Por que un modulo y no un fixture: los tests del worker importan
``io.StringIO`` y parchean ``sys.stdin``/``sys.stdout``, asi que un
fixture pytest con scope "function" añadiria ceremonia sin beneficio.
Una funcion helper es mas directa y deja el ``import`` explicito en
el test (mejor trazabilidad de quien usa el mock).

Convencion: el modulo es PRIVADO al paquete de tests (prefijo ``_``).
NO se importa desde ``src/`` ni desde el codigo de produccion.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock


def build_fake_ts(
    portal: MagicMock | None = None,
    *,
    attach_side_effect: BaseException | None = None,
    attach_return_value: Any = None,
) -> MagicMock:
    """Crea un mock de ``siemens_tia_scripting`` para los tests del worker.

    Args:
        portal: mock de portal a devolver desde ``attach_portal``. Si
            es ``None``, se crea uno por defecto con
            ``get_process_id.return_value=12345`` y un ``detach()``
            mockeado.
        attach_side_effect: excepcion que ``attach_portal`` lanzara
            cuando se invoque. Si se especifica, tiene prioridad sobre
            ``attach_return_value`` (que se ignora).
        attach_return_value: valor de retorno de ``attach_portal`` si
            no hay side effect. Default: el ``portal`` construido (o
            el que paso el caller).

    Returns:
        ``MagicMock`` que imita la superficie de ``siemens_tia_scripting``
        que el worker necesita. Tests que necesitan otra superficie
        (e.g. ``Enums.PortalMode.WithHiddenMainWindow``) pueden
        mutar el mock despues de llamar a este helper.
    """
    ts = MagicMock(name="FakeSiemensWrapper")

    # PortalMode con ``spec=`` para que ``getattr(ts.Enums.PortalMode,
    # nombre_invalido)`` lance ``AttributeError``. Asi el codepath
    # defensivo de ``_handle_attach`` (que captura ``AttributeError`` y
    # devuelve un error con el mensaje "PortalMode invalido...") se
    # ejercita en tests. Sin ``spec=``, MagicMock auto-crea atributos
    # y ese bug seria invisible a los tests.
    ts.Enums.PortalMode = MagicMock(
        spec=["AnyUserInterface", "WithGraphicalUserInterface",
              "WithoutGraphicalUserInterface"],
        name="FakePortalModeEnum",
    )
    ts.Enums.PortalMode.AnyUserInterface = "AnyUserInterface"
    ts.Enums.PortalMode.WithGraphicalUserInterface = (
        "WithGraphicalUserInterface"
    )
    ts.Enums.PortalMode.WithoutGraphicalUserInterface = (
        "WithoutGraphicalUserInterface"
    )

    # Portal por defecto (tests pueden sobreescribir get_process_id o
    # hacer portal.detach.side_effect = ...).
    if portal is None:
        portal = MagicMock(name="FakePortal")
        portal.detach = MagicMock()
        portal.get_process_id = MagicMock(return_value=12345)

    if attach_side_effect is not None:
        ts.attach_portal.side_effect = attach_side_effect
    else:
        ts.attach_portal.return_value = (
            attach_return_value if attach_return_value is not None else portal
        )

    return ts
