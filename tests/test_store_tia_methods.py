"""Regresion (Fase 3.3, sept-2026): ``store.refreshTiaConnection``
ya NO existe (se elimino en el refactor in-place de ``store.js``).

Historia:
  - Regresion original (2026-09-05): ``store.refreshTiaConnection``
    debia existir como metodo del store para que el polling de
    ``main.js`` (``store.refreshTiaConnection?.()``) funcionase.
  - 1.3.1 (Fase 1): el polling se elimino; el estado de TIA pasa a
    llegar por SSE.  ``refreshTiaConnection`` queda como codigo
    muerto en ``store.js``.
  - 3.3.1 (esta): se elimina ``refreshTiaConnection`` de ``store.js``
    (funcion + export del ``Object.assign(store, ...)``) y de los
    tests que asumian su existencia.

Este test verifica que tras el refactor:
  1. ``store.js`` NO exporta ``refreshTiaConnection`` como funcion
     independiente.
  2. ``Object.assign(store, ...)`` NO incluye ``refreshTiaConnection``
     (solo ``connectTia`` y ``disconnectTia``).
  3. ``main.js`` sigue SIN tener el polling legacy
     (``store.refreshTiaConnection?.()``).
  4. ``main.js`` sigue cableando el SSE que consume el stream
     (``new EventSource("/api/v1/stream")`` + ``sse.onmessage``).
"""
from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
STORE_JS = (
    REPO_ROOT
    / "interfaces"
    / "web_server"
    / "static"
    / "js"
    / "store.js"
)
MAIN_JS = (
    REPO_ROOT / "interfaces" / "web_server" / "static" / "js" / "main.js"
)


def _read(path: Path) -> str:
    assert path.exists(), f"Missing file: {path}"
    return path.read_text(encoding="utf-8")


def test_store_object_assign_exposes_only_active_tia_helpers() -> None:
    """Tras Fase 3.3: el ``Object.assign(store, ...)`` solo expone
    ``connectTia`` y ``disconnectTia`` (NO ``refreshTiaConnection``).

    Patron: el ``Object.assign(store, {...})`` debe aparecer DESPUES
    de la declaracion del ``store`` (``export const store = reactive(...)``)
    y ANTES del ``export default store``.
    """
    import re
    text = _read(STORE_JS)

    # Sanity: las 2 funciones que SIGUEN exportadas existen.
    assert "export async function connectTia" in text, (
        "store.js debe exportar connectTia como funcion."
    )
    assert "export async function disconnectTia" in text, (
        "store.js debe exportar disconnectTia como funcion."
    )

    # ``refreshTiaConnection`` ya NO debe estar exportada.
    assert "export async function refreshTiaConnection" not in text, (
        "store.js NO debe exportar refreshTiaConnection: la funcion "
        "se elimino en Fase 3.3 (el polling se quito en 1.3.1, el "
        "estado llega via SSE)."
    )

    # El Object.assign(store, {...}) debe incluir SOLO connectTia y
    # disconnectTia, NO refreshTiaConnection.
    pattern = re.compile(
        r"Object\.assign\s*\(\s*store\s*,\s*\{([^}]*)\}\s*\)",
        re.DOTALL,
    )
    matches = pattern.findall(text)
    assert matches, (
        "store.js debe tener un Object.assign(store, {...}) que "
        "exponga los helpers de TIA como metodos del store. Sin "
        "esto, callers como `store.connectTia?.()` en main.js son "
        "silenciosamente skipeados."
    )
    combined = " ".join(matches)
    assert "connectTia" in combined, (
        "Object.assign(store, ...) debe incluir connectTia."
    )
    assert "disconnectTia" in combined, (
        "Object.assign(store, ...) debe incluir disconnectTia."
    )
    assert "refreshTiaConnection" not in combined, (
        "Object.assign(store, ...) NO debe incluir "
        "refreshTiaConnection (eliminado en Fase 3.3)."
    )


def test_main_js_no_polling_uses_sse() -> None:
    """Regresion 1.3.1 + 3.3.1: el polling de TIA se elimino.

    ``main.js``:
      1. NO tiene el polling legacy ``store.refreshTiaConnection?.()``
         (codigo muerto desde 1.3.1, helper eliminado en 3.3.1).
      2. SI tiene el ``EventSource`` que consume el SSE.
      3. El handler ``onmessage`` parsea y actualiza el store.
    """
    text = _read(MAIN_JS)
    # El polling legacy ya no debe existir.
    assert "store.refreshTiaConnection?.()" not in text, (
        "main.js NO debe tener `store.refreshTiaConnection?.()`. "
        "El polling de TIA se elimino en 1.3.1; el estado llega "
        "via SSE."
    )
    # El SSE debe estar cableado.
    assert 'new EventSource("/api/v1/stream")' in text, (
        "main.js debe abrir un EventSource contra /api/v1/stream."
    )
    assert "sse.onmessage" in text, (
        "main.js debe tener un handler sse.onmessage que parsee "
        "los eventos."
    )


def test_store_object_assign_does_not_contain_refresh_tia_connection() -> None:
    """Anti-regresion: tras 3.3.1, el ``Object.assign(store, ...)``
    NO debe contener ``refreshTiaConnection``.

    Antes de 3.3.1 este test fallaba (la regresion positiva pedia
    que SI estuviera).  Ahora la polaridad se invierte: SI se
    reintroduce ``refreshTiaConnection`` (regresion al estado
    pre-3.3.1), este test rompe.
    """
    text = _read(STORE_JS)
    assert "Object.assign(store" in text, (
        "store.js debe seguir teniendo un Object.assign(store, ...) "
        "para los helpers de TIA."
    )
    # Buscamos especificamente la combinacion: el Object.assign(store)
    # que contenga refreshTiaConnection.  Si lo contiene, regresion.
    import re
    pattern = re.compile(
        r"Object\.assign\s*\(\s*store\s*,\s*\{[^}]*refreshTiaConnection[^}]*\}\s*\)",
        re.DOTALL,
    )
    match = pattern.search(text)
    assert not match, (
        "store.js NO debe tener un Object.assign(store, ...) que "
        "incluya refreshTiaConnection: la funcion se elimino en "
        "Fase 3.3 (el polling se quito en 1.3.1, el estado llega "
        "via SSE)."
    )
