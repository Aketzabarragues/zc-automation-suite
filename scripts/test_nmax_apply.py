"""Test directo del apply de N_MAX contra TIA Portal real.

Bypassea la SPA, el web server y el MCP server. Llama directamente
al TIAProcessGateway con la misma l\u00f3gica que usa el use case
``SyncDispositivosInstancesUseCase.ejecutar_transaccion`` (en su
modo bypass: solo N_MAX, devices desactivados).

Uso (desde la ra\u00edz del proyecto):
    python scripts/test_nmax_apply.py ZC_PLC_STD

El script:
  1. Crea TIAProcessGateway y ConfigManager.
  2. Setea dimensiones de test (todas a 99) en AppState.
  3. Construye el use case y llama ejecutar_transaccion(plc_name, {}).
  4. Captura y muestra el error completo (incluyendo stderr del
     worker) si algo falla.
  5. Si funciona, muestra el resultado de la transacci\u00f3n.

Si el error UTF-8 sigue apareciendo, el stderr del worker (que
ahora se adjunta al RuntimeError) dar\u00e1 la traza exacta de
d\u00f3nde viene el byte 0xe1.
"""
from __future__ import annotations

import asyncio
import sys
import traceback
from pathlib import Path

# Forzar UTF-8 en stdout/stderr para evitar problemas de
# codificaci\u00f3n al mostrar la salida en la consola Windows.
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, Exception):
        pass


# A\u00f1adir el directorio ra\u00edz al path para que `from application...` funcione
# sin necesidad de instalar el proyecto.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


from core.application.state import get_app_state
from areas.alimentacion.application.use_cases.sync_dispositivos_instances import (
    SyncDispositivosInstancesUseCase,
)
from core.infrastructure.config_manager import ConfigManager
from core.infrastructure.gateway import TIAProcessGateway


async def main(plc_name: str) -> int:
    print(f"=== Test directo: apply N_MAX online ===")
    print(f"PLC: {plc_name}")
    print()

    # 1. Crear dependencias.
    gateway = TIAProcessGateway(timeout=120.0)
    config = ConfigManager("infrastructure/config.json")
    state = get_app_state()

    # 2. Settear dimensiones de test (todos a 99) en AppState.
    #    ``DimensionesDispositivos`` es frozen=True, así que no se
    #    puede mutar; construimos una instancia nueva y la
    #    reemplazamos vía ``object.__setattr__`` (que bypassea el
    #    frozen). Esto garantiza que el diff de N_MAX detecta
    #    cambios respecto a los valores actuales del PLC (que son 5).
    from areas.alimentacion.domain.models.dispositivos import DimensionesDispositivos
    new_dims = DimensionesDispositivos(
        num_disp_ed=99, num_disp_ea=99, num_disp_sa=99,
        num_disp_v=99, num_disp_m=99, num_disp_m_vf=99,
    )
    object.__setattr__(state, "dimensiones", new_dims)
    print(f"Desired N_MAX (en AppState):")
    print(f"  ED={new_dims.num_disp_ed}, EA={new_dims.num_disp_ea}, "
          f"SA={new_dims.num_disp_sa}, V={new_dims.num_disp_v}, "
          f"M={new_dims.num_disp_m}, M_VF={new_dims.num_disp_m_vf}")
    print()

    # 3. Construir el use case y ejecutar.
    use_case = SyncDispositivosInstancesUseCase(
        gateway=gateway, config_manager=config, state=state
    )

    print(f"Llamando a ejecutar_transaccion('{plc_name}', {{}})...")
    print()
    try:
        result = await use_case.ejecutar_transaccion(plc_name, {})
    except RuntimeError as exc:
        print(f"\u274c RuntimeError capturado:")
        print(str(exc))
        print()
        # Si el error viene del worker, intentamos separar el stderr
        # del error (si lo hubiera).
        msg = str(exc)
        if " | STDERR: " in msg:
            main_err, stderr = msg.split(" | STDERR: ", 1)
            print(f"  Error del worker: {main_err}")
            print(f"  STDERR del worker (truncado a 2000 chars):")
            print(stderr)
        print()
        print("Traceback local:")
        traceback.print_exc()
        return 1
    except Exception as exc:
        print(f"\u274c Excepci\u00f3n inesperada: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return 1

    print(f"\u2705 Resultado: {result}")
    return 0


if __name__ == "__main__":
    plc = sys.argv[1] if len(sys.argv) > 1 else "ZC_PLC_STD"
    raise SystemExit(asyncio.run(main(plc)))
