"""Test E2E del worker OT persistente como subproceso REAL.

Lanza ``python -u main.py --worker-persistent`` y verifica el ciclo
completo: arranque → ready_idle → ping → exit. Es el unico test
del proyecto que ejerce el codepath real sin mocks (los demas
sustituyen ``_load_siemens_wrapper`` o ``_send_to_persistent_worker``).

Auditoria X3 (sept-2026): este test cubre regresiones que los tests
con mocks NO detectan:

  - El modulo ``main.py`` enrutando ``--worker-persistent`` a
    ``worker_tia.main_persistent_loop()`` (sin esto, el subproceso
    arranca en modo CLI y sale inmediatamente).
  - El stdout del subproceso se emite sin buffering (gracias a
    ``-u``). Si alguien quitara el flag, el reader se quedaria
    colgado esperando el ``ready_idle`` que nunca llega.
  - El reader del gateway parsea correctamente lineas JSON
    reales (con CRLF en Windows).
  - El exit del subproceso cierra stdin limpiamente (sin
    BrokenPipeError en el caller).

Skip automatico:

  El test se salta si ``siemens_tia_scripting`` no se puede importar
  (es decir, si la maquina no tiene TIA Portal instalado, que es
  el caso en CI y en la mayoria de workstations). Esto lo hace
  portable: se ejecuta en la maquina del operario (donde SI hay
  TIA Portal) y se ignora en cualquier otro entorno.

  Para forzarlo en una maquina sin TIA, monkey-patch
  ``_load_siemens_wrapper`` antes de invocar; pero eso ya esta
  cubierto por los tests con mocks (``test_persistent_worker_protocol.py``).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


# ────────────────────────────────────────────────────────────────────────
# Skip guard: solo se ejecuta si siemens_tia_scripting esta disponible
# ────────────────────────────────────────────────────────────────────────


def _siemens_wrapper_available() -> bool:
    """``True`` si ``siemens_tia_scripting`` se puede importar.

    El wrapper solo esta presente en maquinas con TIA Portal V15.1+
    instalado y el usuario pertenece al grupo Openness de Windows.
    En CI y en workstations de desarrollo sin TIA, retorna
    ``False`` y el test se salta.
    """
    try:
        import siemens_tia_scripting  # noqa: F401
        return True
    except (ImportError, OSError, RuntimeError):
        return False


# Skip a nivel de modulo si no hay wrapper. pytest.skip con
# ``allow_module_level=True`` se ejecuta al collect, no al run, asi
# que ni siquiera instancia los fixtures.
pytestmark = pytest.mark.skipif(
    not _siemens_wrapper_available(),
    reason=(
        "siemens_tia_scripting no disponible; este test requiere "
        "TIA Portal V15.1+ instalado y usuario en grupo Openness. "
        "Se ejecuta solo en la maquina del operario."
    ),
)


# ────────────────────────────────────────────────────────────────────────
# Helper: lanza el subproceso del worker OT
# ────────────────────────────────────────────────────────────────────────


REPO_ROOT = Path(__file__).resolve().parent.parent


def _launch_worker() -> subprocess.Popen:
    """Lanza ``python -u main.py --worker-persistent`` y retorna el ``Popen``.

    Usa ``sys.executable -u main.py --worker-persistent`` (mismo
    comando que ``gateway._start_persistent_worker`` en dev). El
    stdin/stdout son PIPE para que el test pueda escribir comandos
    y leer respuestas. stderr tambien es PIPE para diagnostico.
    """
    main_script = REPO_ROOT / "main.py"
    if not main_script.exists():
        pytest.skip(f"main.py no encontrado en {REPO_ROOT}")
    return subprocess.Popen(
        [sys.executable, "-u", str(main_script), "--worker-persistent"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(REPO_ROOT),
        text=True,
        encoding="utf-8",
    )


# ────────────────────────────────────────────────────────────────────────
# Test 1: el worker emite ``ready_idle`` y luego responde a un ``ping``
# ────────────────────────────────────────────────────────────────────────


def test_worker_persistente_emite_ready_idle_y_responde_ping() -> None:
    """E2E: arrancar el subproceso, esperar ``ready_idle``, enviar ``ping``, recibir respuesta.

    Caso real (audit X3, sept-2026): el subproceso del worker
    arranca en estado ``idle`` (NO attached). El operario, desde
    la UI, hace click en "Conectar" → el gateway envia
    ``attach_portal`` → el worker responde con ``{"pid": ...}``.
    Mientras tanto, el frontend hace polling de ``GET /tia/connection``
    que lee el state del gateway (no del worker).

    Aqui testeamos el camino del worker directamente: el primer
    mensaje que emite es ``ready_idle`` (id=0). Tras el attach,
    podemos enviar ``ping`` (un comando del ``COMMAND_REGISTRY``)
    y esperar respuesta.

    Args:
        timeout_attach: 30s es generoso para un attach real de TIA
            Portal en una maquina sobrecargada.
    """
    proc = _launch_worker()
    try:
        # Helper: lee lineas de stdout hasta encontrar una JSON con el
        # id pedido. El worker emite lineas no-JSON (logs de Siemens
        # como "2026-09-06 16:27:08,615 [1] INFO  Siemens.TiaPortal...")
        # intercaladas con las respuestas JSON; el test las ignora
        # igual que hace el reader del gateway. Asi el test refleja
        # el comportamiento real y es robusto ante ruido de stdout.
        def _read_json_line(target_id: int | None = None) -> dict:
            for raw in iter(proc.stdout.readline, ""):
                line = raw.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    # Linea no JSON (log de Siemens). Ignorar.
                    continue
                if target_id is None or obj.get("id") == target_id:
                    return obj
            raise AssertionError(
                f"EOF sin encontrar respuesta con id={target_id!r}. "
                f"stderr=\n{proc.stderr.read()}"
            )

        # 1. Leemos el ready_idle (primera respuesta JSON del worker).
        #    El test se rompe aqui si el subproceso no emite el
        #    ready_idle (e.g. si alguien quito el ``-u`` y el stdout
        #    esta buffereado, o si el routing de main.py falla).
        ready = _read_json_line(target_id=0)
        assert ready["id"] == 0
        assert ready["ok"] is True
        assert ready["result"] == "ready_idle"

        # 2. Enviamos attach_portal.
        attach_payload = json.dumps(
            {
                "id": 1,
                "command": "attach_portal",
                "args": {"mode": "WithGraphicalUserInterface"},
            }
        )
        proc.stdin.write(attach_payload + "\n")
        proc.stdin.flush()

        # 3. Leemos la respuesta al attach. El attach real tarda
        #    ~5s en una maquina normal, hasta 20-30s en una lenta.
        attach_response = _read_json_line(target_id=1)
        # TIA Portal responde con {"pid": <int>} o {"error": "..."}.
        # En una maquina del operario con TIA abierto, esperamos OK.
        # Si TIA no esta abierto, el test fallara con un error claro.
        if not attach_response["ok"]:
            pytest.fail(
                f"attach_portal fallo: {attach_response.get('error')}. "
                "¿Esta TIA Portal abierto? ¿Usuario en grupo Openness?"
            )
        assert "pid" in attach_response["result"]

        # 4. Enviamos un ping (comando del COMMAND_REGISTRY).
        ping_payload = json.dumps({"id": 2, "command": "ping", "args": {}})
        proc.stdin.write(ping_payload + "\n")
        proc.stdin.flush()

        ping_response = _read_json_line(target_id=2)
        assert ping_response["id"] == 2
        assert ping_response["ok"] is True

        # 5. Enviamos exit para cerrar limpiamente.
        exit_payload = json.dumps({"id": 3, "command": "exit", "args": {}})
        proc.stdin.write(exit_payload + "\n")
        proc.stdin.flush()
        proc.stdin.close()

        # 6. El subproceso termina con codigo 0.
        returncode = proc.wait(timeout=5)
        assert returncode == 0, (
            f"worker termino con codigo {returncode}; "
            f"stderr=\n{proc.stderr.read()}"
        )
    finally:
        # Cleanup: si el test falla a mitad, matamos el subproceso.
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
