"""Tests de regresion para la firma de ``register_alimentacion``.

Historia
--------
Tras la migracion de ``self._log`` (LogBuffer) a ``logger`` (Python
stdlib) en los FBs de alimentacion (commit ``a91bbf9``), la funcion
``register_alimentacion`` dejo de aceptar el kwarg ``log=`` (los FBs
usan ``logger = logging.getLogger(__name__)`` directamente y el
bridge ``log_web_bridge`` enruta los records >= ``WEB_LEVEL`` al
LogBuffer Singleton automaticamente).

El supervisor (``core.launcher.main_supervisor._build_components``)
sigue pasando ``log=get_log_buffer()`` por el call site, lo que
rompe en runtime con::

    TypeError: register() got an unexpected keyword argument 'log'

Estos tests capturan el bug en 2 sitios:

  1. La firma de ``register_alimentacion`` NO debe aceptar ``log``.
  2. El call site en ``_build_components`` NO debe pasar ``log=``.

Si el supervisor o la firma vuelven a meter el kwarg por error de
refactor, los tests rompen.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest


def _resolve_repo_root() -> Path:
    """Devuelve la raiz del repo (un nivel por encima de ``tests/``)."""
    return Path(__file__).resolve().parent.parent


# ── Test 1: firma de register_alimentacion ───────────────────────────


def test_register_alimentacion_signature_no_log_kwarg() -> None:
    """``register_alimentacion`` no debe aceptar ``log`` como kwarg.

    Antes de la migracion a ``self._log`` -> ``logger``, register()
    aceptaba ``log=`` para inyectar el LogBuffer a cada FB. Tras el
    refactor (commits ``a91bbf9`` + ``0ac7f5f``), los FBs usan
    directamente el logger del modulo y el bridge enruta al LogBuffer,
    por lo que el kwarg ya no tiene sentido y debe haberse eliminado.
    """
    from areas.alimentacion import register as register_alimentacion

    sig = inspect.signature(register_alimentacion)
    param_names = list(sig.parameters.keys())
    assert "log" not in param_names, (
        f"register_alimentacion no debe aceptar 'log' tras migracion a "
        f"logger. Parametros actuales: {param_names}"
    )


def test_register_alimentacion_signature_expected_kwargs() -> None:
    """Lock de la firma actual para detectar drift futuro.

    Si esto rompe, alguien anadio/quito un kwarg sin actualizar este
    test (que documenta la API publica de ``register_alimentacion``).
    """
    from areas.alimentacion import register as register_alimentacion

    sig = inspect.signature(register_alimentacion)
    expected = {"engine", "config_manager", "tia_client", "build_cache", "app_state"}
    actual = set(sig.parameters.keys())
    assert actual == expected, (
        f"Firma de register_alimentacion cambio. "
        f"Esperado: {sorted(expected)}, actual: {sorted(actual)}"
    )


# ── Test 2: call site en _build_components ─────────────────────────────


def _extract_register_alimentacion_call(source: str) -> str | None:
    """Extrae el bloque ``register_alimentacion(...)`` del codigo fuente.

    Busca el primer call site (formato multilinea con argumentos en
    varias lineas, como esta en ``_build_components``).
    """
    # Patrón: empieza con ``register_alimentacion(`` y termina con ``)``
    # en la siguiente linea que solo contiene ``)``.
    start = source.find("register_alimentacion(")
    if start < 0:
        return None
    # Busca el cierre balanceando paréntesis desde start.
    depth = 0
    for i in range(start, len(source)):
        ch = source[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return source[start : i + 1]
    return None


def test_build_components_call_site_has_no_log_kwarg() -> None:
    """``_build_components`` no debe pasar ``log=`` a ``register_alimentacion``.

    Repro del bug visto en vivo (smoke test del .exe, 2026-09-17):

        [ERROR] [zc.main] start: _build_components() fallo:
          register() got an unexpected keyword argument 'log'

    Causa: el kwarg se quito de la firma pero quedo en el call site.
    El supervisor llama ``register_alimentacion(engine, ...,
    log=get_log_buffer())`` aunque register ya no acepta log.
    """
    src_path = (
        _resolve_repo_root()
        / "core"
        / "launcher"
        / "main_supervisor.py"
    )
    src = src_path.read_text(encoding="utf-8")
    call_text = _extract_register_alimentacion_call(src)
    assert call_text is not None, (
        f"No se encontro call site a register_alimentacion() en {src_path}. "
        f"¿Se renombro la funcion?"
    )
    assert "log=" not in call_text, (
        f"register_alimentacion() no debe recibir 'log=' tras la migracion "
        f"a logger. Call site encontrado:\n{call_text}"
    )


def test_build_components_imports_get_log_buffer_for_wire_all() -> None:
    """``get_log_buffer`` sigue usandose para ``wire_all`` aunque
    ``register_alimentacion`` ya no lo acepte.

    Tras quitar ``log=`` del call site, ``get_log_buffer`` debe
    seguir importado (porque ``wire_all(log_buffer=...)`` lo usa).
    Si alguien borra el import pensando que ya no hace falta, este
    test lo detecta antes de que el supervisor reviente en runtime.
    """
    src_path = (
        _resolve_repo_root()
        / "core"
        / "launcher"
        / "main_supervisor.py"
    )
    src = src_path.read_text(encoding="utf-8")
    assert "from core.runtime.log_buffer import get_log_buffer" in src, (
        f"Falta el import top-level de get_log_buffer en {src_path}. "
        f"Lo necesita wire_all(log_buffer=...) tras la migracion."
    )
    # Verifica que efectivamente se usa (al menos una llamada).
    assert src.count("get_log_buffer()") >= 1, (
        f"get_log_buffer() no se llama en {src_path}, pero sigue "
        f"importado. Limpia el import si ya no se necesita."
    )


# ── Test bonus: call site en otros archivos ───────────────────────────


@pytest.mark.parametrize(
    "relative_path",
    [
        "core/launcher/main_supervisor.py",
    ],
)
def test_no_legacy_log_kwarg_in_call_sites(relative_path: str) -> None:
    """Lock global: ningun call site a ``register_alimentacion`` debe
    pasar ``log=``.

    Hoy solo hay 1 call site (en ``main_supervisor._build_components``).
    Si en el futuro se añade un segundo call site, este test se
    ajusta o se parametriza. Por ahora single-site es correcto.
    """
    src_path = _resolve_repo_root() / relative_path
    src = src_path.read_text(encoding="utf-8")
    call_text = _extract_register_alimentacion_call(src)
    if call_text is None:
        pytest.skip(f"Sin call site a register_alimentacion en {relative_path}")
    assert "log=" not in call_text, (
        f"Legacy kwarg 'log=' encontrado en call site de "
        f"register_alimentacion en {relative_path}.\n{call_text}"
    )
