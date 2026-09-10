"""Regresion (2026-09-05): ``store.refreshTiaConnection`` debe existir
como metodo del store.

Bug original: en ``main.js:267``, el polling del estado de TIA
hace ``store.refreshTiaConnection?.()``. Pero la funcion
``refreshTiaConnection`` se exportaba como funcion independiente
en ``store.js:675`` y NUNCA se asignaba al objeto ``store``. El
operador ``?.()`` skipeaba la llamada silenciosamente, asi que el
polling de TIA NUNCA ha funcionado desde PR 5b (sept-2025).

Este test verifica que tras el fix, el store SÍ expone las 3
funciones clave (refreshTiaConnection, connectTia, disconnectTia)
como metodos, para que ``store.foo?.()`` funcione en el browser.
"""
from __future__ import annotations

from pathlib import Path

import pytest

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


def test_store_object_assign_exposes_tia_helpers() -> None:
    """El archivo ``store.js`` debe hacer ``Object.assign(store, ...)``
    (o equivalente) que exponga ``refreshTiaConnection``,
    ``connectTia`` y ``disconnectTia`` como metodos del ``store``.

    Patron: el ``Object.assign(store, {...})`` debe aparecer DESPUES
    de la declaracion del ``store`` (``export const store = reactive(...)``)
    y ANTES del ``export default store``.
    """
    text = _read(STORE_JS)

    # Sanity: las 3 funciones existen como exports independientes.
    assert "export async function refreshTiaConnection" in text, (
        "store.js debe exportar refreshTiaConnection como funcion."
    )
    assert "export async function connectTia" in text, (
        "store.js debe exportar connectTia como funcion."
    )
    assert "export async function disconnectTia" in text, (
        "store.js debe exportar disconnectTia como funcion."
    )

    # El Object.assign(store, {...}) debe incluir las 3 funciones.
    import re
    # Busca un Object.assign(store, { ... }) o similar, y verifica
    # que las 3 funciones aparecen dentro del objeto.
    pattern = re.compile(
        r"Object\.assign\s*\(\s*store\s*,\s*\{([^}]*)\}\s*\)",
        re.DOTALL,
    )
    matches = pattern.findall(text)
    assert matches, (
        "store.js debe tener un Object.assign(store, {...}) que "
        "exponga los helpers de TIA como metodos del store. Sin "
        "esto, callers como `store.refreshTiaConnection?.()` en "
        "main.js son silenciosamente skipeados."
    )
    # Verifica que las 3 funciones estan en el Object.assign.
    combined = " ".join(matches)
    assert "refreshTiaConnection" in combined
    assert "connectTia" in combined
    assert "disconnectTia" in combined


def test_main_js_polling_uses_store_dot_method() -> None:
    """Regresión 1.3.1: el polling de TIA se eliminó. Ahora el SSE
    actualiza el store directamente. Verificamos que main.js:
      1. NO tiene el polling legacy ``store.refreshTiaConnection?.()``
         (es código muerto desde 1.3.1).
      2. SÍ tiene el ``EventSource`` que consume el SSE.
      3. El handler ``onmessage`` parsea y actualiza el store.
    """
    text = _read(MAIN_JS)
    # El polling legacy ya no debe existir.
    assert "store.refreshTiaConnection?.()" not in text, (
        "main.js NO debe tener `store.refreshTiaConnection?.()`. "
        "El polling de TIA se eliminó en 1.3.1; el estado llega "
        "vía SSE."
    )
    # El SSE debe estar cableado.
    assert 'new EventSource("/api/v1/stream")' in text, (
        "main.js debe abrir un EventSource contra /api/v1/stream."
    )
    assert "sse.onmessage" in text, (
        "main.js debe tener un handler sse.onmessage que parsee "
        "los eventos."
    )


def test_store_has_no_tia_methods_before_fix_pattern() -> None:
    """Anti-regresion: si alguien quita el Object.assign de store.js
    (reintroduciendo el bug), el texto del archivo NO debe contener
    la firma de la proteccion. Esto es un test debil pero detecta
    el caso obvio de que alguien borre el fix sin querer.
    """
    text = _read(STORE_JS)
    # El patron clave que indica que el fix esta aplicado:
    # hay un Object.assign(store, ...) que incluye refreshTiaConnection.
    assert "Object.assign(store" in text and "refreshTiaConnection" in text, (
        "store.js debe tener Object.assign(store, ...) que incluya "
        "refreshTiaConnection. Si esto se borra, el polling de TIA "
        "en main.js dejara de funcionar (mismo bug del 2026-09-05)."
    )
