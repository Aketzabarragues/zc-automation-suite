"""Smoke para verificar que FunctionBase.tick() emite el traceback al _log del FB cuando hay excepcion."""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from core.composition.plc_function_base import FunctionBase


class _StubLog:
    def __init__(self):
        self.messages = []

    def info(self, m): self.messages.append(("info", m))
    def success(self, m): self.messages.append(("success", m))
    def error(self, m): self.messages.append(("error", m))
    def warning(self, m): self.messages.append(("warning", m))


class _BoomFB(FunctionBase):
    STEP_TIMEOUT_S = 5.0

    async def run_step(self, idx, **params):
        raise RuntimeError("boom test error")


async def main():
    fb = _BoomFB(nombre="boom_fb", titulo="Boom", steps=[{"nombre": "step_1"}])
    fb._log = _StubLog()  # stub en lugar del singleton para el test

    started = await fb.start(x=1)
    assert started
    while not fb.is_terminal():
        await fb.tick()
    assert fb.nStep == fb.n_error, f"nStep={fb.nStep}"

    print("OK: FB termino en n_error")
    print(f"Messages emitted to _log ({len(fb._log.messages)}):")
    for level, m in fb._log.messages:
        truncated = m[:120] + "..." if len(m) > 120 else m
        print(f"  [{level}] {truncated}")

    error_msgs = [m for l, m in fb._log.messages if l == "error"]
    assert error_msgs, "no se emitio error_msg al _log"
    assert "boom test error" in error_msgs[0], "error_msg no contiene el mensaje original"
    assert "Traceback" in error_msgs[0], "traceback no presente en _log"
    print("\nOK: traceback completo emitido al _log del FB (ConsolaLogs lo verá)")


asyncio.run(main())
