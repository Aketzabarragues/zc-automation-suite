"""Tests del shutdown handler X2 del worker OT persistente.

Cubre el bug X2 de la auditoria post-implementacion del worker
persistente: sin shutdown handler, al pulsar "Detener web" desde el
tray el subproceso del worker quedaba zombi (~200 MB con
``siemens_tia_scripting.pyd`` cargado) hasta que se cerrase TIA o se
matase manualmente.

Tres redes de seguridad, en este orden de prioridad:

  1. **Lifespan de FastAPI** (``interfaces/web_server/app.py::_tia_lifespan``):
     path canónico. Se invoca automáticamente al shutdown de uvicorn.
  2. **Finally del supervisor** (``launcher/web_supervisor.py::_serve_once``):
     red de seguridad por si uvicorn crashea antes del lifespan.
  3. **Finally de main.py** (``main.py::_run_web_mode_async``): red
     adicional para ``python main.py --web`` directo (sin supervisor).

Verificamos que:

  - El lifespan llama a ``gateway.disconnect()`` exactamente UNA vez
    al shutdown cuando el gateway es persistente.
  - El lifespan NO llama a ``disconnect()`` cuando el gateway es
    1-shot (``persistent=False``; el ``disconnect()`` lanzaria
    ``TIAConnectionError`` y eso es el comportamiento esperado del
    gateway).
  - El lifespan NO falla (no enmascara el shutdown) si
    ``disconnect()`` lanza una excepción.
  - El supervisor limpia ``self._gateway`` en el finally si el
    gateway es persistente y callable (regresion X2).
  - El supervisor no rompe el path normal cuando el gateway no
    expone ``disconnect`` (test fake del supervisor sin ``disconnect``).
"""
from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from core.infrastructure.gateway import TIAProcessGateway  # noqa: E402
from interfaces.web_server.app import create_app  # noqa: E402


# ── Helpers ───────────────────────────────────────────────────────


def _build_app_with_lifespan(gateway: MagicMock) -> FastAPI:
    """Construye la app usando ``create_app`` (mismo lifespan que produccion).

    Usar ``create_app`` directamente (no replicar el lifespan) es
    importante: cualquier divergencia entre el lifespan del test y el
    de producción anula el valor del test. Si refactorizas el
    lifespan, este test sigue siendo valido porque va por la via
    publica.
    """
    return create_app(gateway=gateway)


# ── Test 1: lifespan llama a disconnect al shutdown (persistent) ─


def test_lifespan_llama_disconnect_al_shutdown_persistent() -> None:
    """El lifespan de FastAPI llama a ``gateway.disconnect()`` al
    shutdown si el gateway es persistente (cubrir el bug X2).

    Patron: ``TestClient(app)`` como context manager. Al salir del
    ``with`` se dispara el shutdown de la app, que ejecuta el
    codigo post-``yield`` del lifespan.
    """
    gateway = MagicMock(spec=TIAProcessGateway)
    gateway.persistent = True
    gateway.disconnect = AsyncMock()

    app = _build_app_with_lifespan(gateway)
    with TestClient(app) as client:
        # Cualquier request fuerza el startup del lifespan.
        resp = client.get("/api/v1/areas")
        assert resp.status_code == 200

    # Al salir del ``with``, uvicorn dispara el shutdown, lo que
    # ejecuta el codigo post-``yield`` del lifespan y por tanto
    # llama a ``gateway.disconnect()``.
    gateway.disconnect.assert_awaited_once()


# ── Test 2: lifespan NO llama a disconnect si persistent=False ───


def test_lifespan_no_llama_disconnect_si_no_persistent() -> None:
    """El lifespan NO llama a ``disconnect()`` cuando el gateway es
    1-shot (``persistent=False``).

    Razon: ``gateway.disconnect()`` lanza ``TIAConnectionError`` si
    el gateway no es persistente (es parte de su contrato publico:
    "disconnect() solo aplica a gateway.persistent=True"). El
    lifespan debe respetar este contrato y no intentar llamar a un
    metodo que fallaria. El modo 1-shot es el del MCP y NO tiene
    worker persistente que matar.
    """
    gateway = MagicMock(spec=TIAProcessGateway)
    gateway.persistent = False
    # ``disconnect`` se mockea como AsyncMock para que, si por
    # error el lifespan lo llamase, pudiéramos detectarlo via
    # ``assert_awaited_once()`` abajo. Como NO debe llamarse,
    # ``assert_not_awaited()`` valida el contrato.
    gateway.disconnect = AsyncMock()

    app = _build_app_with_lifespan(gateway)
    with TestClient(app):
        pass

    gateway.disconnect.assert_not_awaited()


# ── Test 3: lifespan no enmascara el shutdown si disconnect falla ─


def test_lifespan_no_enmascara_shutdown_si_disconnect_falla(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Si ``gateway.disconnect()`` lanza una excepción, el lifespan
    la absorbe (loguea warning) y NO la propaga.

    Razon: si el shutdown de FastAPI falla porque ``disconnect()``
    peta, uvicorn imprime un traceback ruidoso y el operario cree
    que el apagado fue traumatico cuando en realidad la app se esta
    cerrando igualmente. Loguear el warning y dejar que el shutdown
    continue es lo correcto.
    """
    gateway = MagicMock(spec=TIAProcessGateway)
    gateway.persistent = True
    # ``disconnect`` falla con algo realista (e.g. el subproceso del
    # worker ya estaba muerto y el kill devuelve error).
    gateway.disconnect = AsyncMock(
        side_effect=RuntimeError("subproceso ya muerto")
    )

    app = _build_app_with_lifespan(gateway)

    with caplog.at_level(logging.WARNING, logger="interfaces.web_server.app"):
        with TestClient(app):
            pass

    gateway.disconnect.assert_awaited_once()
    # El warning se emitio con el motivo del fallo.
    assert any(
        "subproceso ya muerto" in record.message
        for record in caplog.records
    ), f"Warnings capturados: {[r.message for r in caplog.records]}"


# ── Test 4: lifespan defensivo si app.state.gateway es None ───────


def test_lifespan_no_falla_si_gateway_no_esta_en_app_state() -> None:
    """El lifespan es defensivo: si por algun motivo ``app.state.gateway``
    no esta seteado, el shutdown NO debe explotar.

    Por que testeamos esto: algunos tests de routers de areas
    instancian ``FastAPI()`` directamente y montan routers sin pasar
    por ``create_app``. En ese caso ``app.state.gateway`` no existe.
    Aunque el bug X2 NO se reproduce en ese path (no hay gateway que
    matar), el lifespan debe ser robusto: getattr + None check.
    """
    app = FastAPI()  # sin create_app, sin gateway en app.state
    # El lifespan se aplica via el constructor de FastAPI solo si lo
    # pasamos explicitamente. Aqui lo inyectamos a mano copiando el
    # contrato de ``create_app`` (mismo lifespan que prod).
    from interfaces.web_server.app import _tia_lifespan
    app.router.lifespan_context = _tia_lifespan  # FastAPI lo recoge aqui

    # No debe explotar al entrar/salir del TestClient.
    with TestClient(app):
        pass
    # Si llegamos aqui, el lifespan defensivo funciona.


# ── Test 5: supervisor llama a disconnect en finally si persistent ─


def test_supervisor_serve_once_llama_disconnect_en_finally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regresion X2: el bloque ``finally`` de ``_serve_once`` llama
    a ``gateway.disconnect()`` aunque uvicorn salga por un path
    anomalo (cubrir el caso "uvicorn crashea antes del lifespan
    cleanup").

    Mockeamos todo lo que toca OT (gateway, create_app, uvicorn) y
    verificamos que al final de ``_serve_once``, ``disconnect`` se
    llamo. Esto es la red de seguridad del supervisor.
    """
    from launcher.web_supervisor import WebServiceSupervisor

    fake_gateway = MagicMock(name="fake_gateway")
    fake_gateway.persistent = True
    fake_gateway.disconnect = AsyncMock()
    fake_gateway._cache = {}
    fake_gateway._bloques_cache = {}
    fake_gateway._dispatch_worker = AsyncMock()
    # ``b82f9d6`` anadio ``asyncio.run(gateway.start())`` al inicio
    # de ``_serve_once`` para arrancar el worker persistente ANTES
    # de uvicorn. ``start()`` debe ser un awaitable para que
    # ``asyncio.run()`` lo consuma; un ``MagicMock`` sync rompe con
    # ``ValueError: a coroutine was expected``. Mismo patron que
    # ``disconnect`` arriba.
    fake_gateway.start = AsyncMock()

    fake_app = MagicMock(name="fake_app")
    fake_server = MagicMock(name="fake_server")
    fake_server.run = MagicMock(return_value=None)
    fake_server.should_exit = False

    # Monkey-patches (importaciones tardias dentro de _serve_once).
    monkeypatch.setattr(
        "core.infrastructure.gateway.TIAProcessGateway",
        lambda **kwargs: fake_gateway,
    )
    monkeypatch.setattr(
        "interfaces.web_server.app.create_app",
        lambda gateway: fake_app,
    )
    monkeypatch.setattr("uvicorn.Config", lambda *a, **kw: MagicMock())
    monkeypatch.setattr("uvicorn.Server", lambda config: fake_server)

    s = WebServiceSupervisor(host="127.0.0.1", port=19999)
    s._serve_once()

    fake_gateway.disconnect.assert_awaited_once()


# ── Test 6: supervisor NO rompe si gateway no tiene disconnect ───


def test_supervisor_serve_once_no_rompe_si_gateway_no_tiene_disconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regresion: si por algun motivo el gateway mockeado en un
    test no expone ``disconnect`` (caso real: ``_FakeGateway`` en
    ``test_serve_once_wires_persistent_true``), el ``finally`` del
    supervisor debe ser tolerante y no lanzar.

    Esto evita que un cambio futuro en el supervisor rompa los
    tests existentes que mockean el gateway de forma minimalista.
    """
    from launcher.web_supervisor import WebServiceSupervisor

    class _MinimalFakeGateway:
        """Sin ``disconnect`` ni ``persistent`` (MagicMock los inyecta
        via ``__getattr__``, pero aqui no usamos MagicMock para
        reflejar el path real de tests que usan clases fake)."""
        def __init__(self, **kwargs):
            self.persistent = kwargs.get("persistent", False)
            self._cache = {}
            self._bloques_cache = {}
            self._dispatch_worker = AsyncMock()
            # ``b82f9d6`` anadio ``asyncio.run(gateway.start())`` al
            # inicio de ``_serve_once`` y, en el exito, lee
            # ``gateway._connection_state`` y ``gateway.is_worker_alive()``
            # para el log. Sin esto el fake no llega al path del
            # ``finally`` que es lo que queremos verificar.
            self.start = AsyncMock()
            self._connection_state = "idle"
            self.is_worker_alive = MagicMock(return_value=True)

    fake_app = MagicMock(name="fake_app")
    fake_server = MagicMock(name="fake_server")
    fake_server.run = MagicMock(return_value=None)
    fake_server.should_exit = False

    monkeypatch.setattr(
        "core.infrastructure.gateway.TIAProcessGateway",
        _MinimalFakeGateway,
    )
    monkeypatch.setattr(
        "interfaces.web_server.app.create_app",
        lambda gateway: fake_app,
    )
    monkeypatch.setattr("uvicorn.Config", lambda *a, **kw: MagicMock())
    monkeypatch.setattr("uvicorn.Server", lambda config: fake_server)

    s = WebServiceSupervisor(host="127.0.0.1", port=19999)
    # No debe lanzar AttributeError ni nada similar.
    s._serve_once()


# ── Test 7: _run_web_mode_async llama a disconnect en finally ────


def test_run_web_mode_async_llama_disconnect_en_finally(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regresion X2 (3a red de seguridad): ``_run_web_mode_async``
    llama a ``gateway.disconnect()`` en su ``finally``, aunque
    ``uvicorn.Server.serve`` se complete normalmente o lance.

    Cubre el path ``python main.py --web`` directo, sin supervisor.

    Por que subprocess: ``main.py`` ejecuta ``sys.stdout.reconfigure``
    a nivel de modulo, lo que rompe la captura de stdout de pytest
    si lo importamos directamente. Usamos subprocess para que el
    test sea fiel al path real (un proceso Python separado que
    importa main) y a la vez no contamine pytest.
    """
    # Sidecar Python que importa main y deja la assertion en
    # ``out.json``. Asi el test principal solo lee el JSON
    # sin tocar la captura de pytest.
    sidecar = tmp_path / "sidecar.py"
    sidecar.write_text(
        r"""
import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

# El repo root se pasa como argv[1] (el sidecar vive en tmp_path
# y su __file__.parent.parent resuelve al temp dir, no al repo).
repo_root = Path(sys.argv[2])
sys.path.insert(0, str(repo_root))

import main as main_mod  # noqa: E402
from interfaces.web_server import app as app_mod  # noqa: E402
import uvicorn  # noqa: E402

fake_gateway = MagicMock(name="fake_gateway")
fake_gateway.persistent = True
fake_gateway.disconnect = AsyncMock()

fake_app = MagicMock(name="fake_app")
fake_server = MagicMock(name="fake_server")


async def _serve_done():
    return None


fake_server.serve = _serve_done

# ``_run_web_mode_async`` hace ``from interfaces.web_server.app
# import create_app`` lazy dentro de la funcion, asi que
# parchear el modulo fuente (no ``main_mod``) es lo correcto.
app_mod.create_app = lambda gateway: fake_app
uvicorn.Config = lambda *a, **kw: MagicMock()
uvicorn.Server = lambda config: fake_server

asyncio.run(main_mod._run_web_mode_async(fake_gateway, "127.0.0.1", 19999))

assert fake_gateway.disconnect.await_count == 1, (
    f"disconnect await_count={fake_gateway.disconnect.await_count} != 1"
)
Path(sys.argv[1]).write_text(json.dumps({"ok": True}))
""",
        encoding="utf-8",
    )

    out_json = tmp_path / "out.json"
    result = subprocess.run(
        [sys.executable, str(sidecar), str(out_json), str(ROOT)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"sidecar fallo (rc={result.returncode}):\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    assert out_json.exists(), "sidecar no escribio out.json"
    assert json.loads(out_json.read_text(encoding="utf-8")) == {"ok": True}


# ── Test 8: _run_web_mode_async absorbe errores de disconnect ────


def test_run_web_mode_async_absorbe_errores_de_disconnect(
    tmp_path: Path,
) -> None:
    """Si ``gateway.disconnect()`` lanza, ``_run_web_mode_async`` la
    absorbe (warning log) y no enmascara el shutdown.

    Misma logica que el test 3 pero para el path de ``main.py``.
    Mismo truco de subprocess que el test 7 para evitar el
    ``sys.stdout.reconfigure`` de ``main.py``.
    """
    sidecar = tmp_path / "sidecar.py"
    sidecar.write_text(
        r"""
import asyncio
import json
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

repo_root = Path(sys.argv[2])
sys.path.insert(0, str(repo_root))

import main as main_mod  # noqa: E402
from interfaces.web_server import app as app_mod  # noqa: E402
import uvicorn  # noqa: E402

# Capturamos todos los warnings/errores que emita cualquier logger.
# Usamos un handler custom enganchado al root para que ``logging.
# getLogger("__main__").warning(...)`` (lo que hace ``main.py``)
# se registre tambien (un logger con nombre != root NO propaga al
# root si su ``propagate`` es False, pero por defecto es True).
log_records = []


class _CaptureHandler(logging.Handler):
    def emit(self, record):
        log_records.append(record)


logging.getLogger().addHandler(_CaptureHandler())
logging.getLogger().setLevel(logging.WARNING)

fake_gateway = MagicMock(name="fake_gateway")
fake_gateway.persistent = True
fake_gateway.disconnect = AsyncMock(
    side_effect=RuntimeError("kill ya consumio el proc")
)

fake_app = MagicMock(name="fake_app")
fake_server = MagicMock(name="fake_server")


async def _serve_done():
    return None


fake_server.serve = _serve_done

app_mod.create_app = lambda gateway: fake_app
uvicorn.Config = lambda *a, **kw: MagicMock()
uvicorn.Server = lambda config: fake_server

# No debe lanzar: la excepcion se absorbe.
asyncio.run(main_mod._run_web_mode_async(fake_gateway, "127.0.0.1", 19999))

assert fake_gateway.disconnect.await_count == 1, (
    f"disconnect await_count={fake_gateway.disconnect.await_count} != 1"
)
# Y se logueo el warning con el motivo (en cualquier logger).
assert any(
    "kill ya consumio el proc" in r.getMessage() for r in log_records
), f"Warnings capturados: {[r.getMessage() for r in log_records]}"
Path(sys.argv[1]).write_text(json.dumps({"ok": True}))
""",
        encoding="utf-8",
    )

    out_json = tmp_path / "out.json"
    result = subprocess.run(
        [sys.executable, str(sidecar), str(out_json), str(ROOT)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"sidecar fallo (rc={result.returncode}):\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    assert out_json.exists(), "sidecar no escribio out.json"
    assert json.loads(out_json.read_text(encoding="utf-8")) == {"ok": True}
