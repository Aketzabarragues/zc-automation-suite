"""Contrato de los estados del worker TIA en el store de la SPA.

El worker TIA publica 6 estados: los 4 estables del contrato
(``connected`` / ``connecting`` / ``idle`` / ``error``) y los
transitorios (``busy`` / ``attaching`` / ``detaching``).

Un transitorio significa "el portal sigue vivo, estoy ejecutando un
comando". El worker emite ``busy`` en CADA comando, incluido el
refresco de cache que hace el FB de apply al terminar. Si el store
tomara ese estado por una desconexion, el HMI sustitutia el panel
entero por el empty state "Conecta a TIA Portal" en mitad de la
operacion.

Este test ejecuta ``store.js`` en Node con un shim de ``reactive``
(Vue no corre en Node) y verifica el contrato:

  * ``store.tiaConnection.state`` es SIEMPRE uno de los 4 estados
    estables.
  * Los transitorios mueven solo el flag ``busy``; no pisan el estado.
  * Un estado desconocido se descarta.
  * El snapshot HTTP aplica lo mismo que el evento SSE.

El driver de Node sale con codigo 1 si falla cualquier comprobacion:
una regresion en ``store.js`` hace fallar este test.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

def _resolve_repo_root() -> Path:
    """Raiz del repo. Sube hasta encontrar ``main.py``.

    Robusto frente a movimientos del test entre subdirectorios
    de ``tests/`` .
    """
    here = Path(__file__).resolve().parent
    for candidate in [here, *here.parents]:
        if (candidate / "main.py").is_file():
            return candidate
    return here.parents[len(here.parents) - 4]


REPO_ROOT = _resolve_repo_root()
JS_DIR = REPO_ROOT / "core" / "web_server" / "static" / "js"

VUE_IMPORT = 'import { reactive } from "/js/vendor/vue.esm-browser.prod.js";'

# Shim de Vue: ``reactive`` sin Proxy es suficiente para el store
# (el test no necesita reactividad, solo el objeto plano).
VUE_SHIM = "export const reactive = (o) => o;\n"

DRIVER = r"""
import { applyTiaState, connectTia, store } from "./store.js";

const ESTABLES = ["connected", "connecting", "idle", "error"];

let fallos = 0;

function check(nombre, cond, extra) {
    if (!cond) {
        fallos += 1;
        console.error("FALLO: " + nombre + (extra ? " :: " + extra : ""));
    }
}

function estado() {
    return store.tiaConnection.state;
}

function busy() {
    return store.tiaConnection.busy;
}

// --- El estado inicial es estable ---
check("estado inicial idle", estado() === "idle", estado());
check("estado inicial sin busy", busy() === false, String(busy()));

// --- SSE: estado estable ---
applyTiaState({ state: "connected" });
check("connected aplica el estado", estado() === "connected", estado());
check("connected limpia busy", busy() === false, String(busy()));

// --- SSE: estado transitorio "busy" ---
applyTiaState({ state: "busy" });
check("busy NO pisa el estado", estado() === "connected", estado());
check("busy activa el flag busy", busy() === true, String(busy()));

applyTiaState({ state: "busy" });
check("busy repetido mantiene busy", busy() === true, String(busy()));

// --- SSE: vuelta al estado estable ---
applyTiaState({ state: "connected" });
check("connected limpia busy", busy() === false, String(busy()));
check("connected conserva el estado", estado() === "connected", estado());

// --- SSE: transitorios del ciclo de vida ---
applyTiaState({ state: "attaching" });
check("attaching NO pisa el estado", estado() === "connected", estado());
check("attaching no activa busy", busy() === false, String(busy()));

applyTiaState({ state: "detaching" });
check("detaching NO pisa el estado", estado() === "connected", estado());
check("detaching no activa busy", busy() === false, String(busy()));

// --- SSE: error ---
applyTiaState({ state: "error" });
check("error aplica el estado", estado() === "error", estado());
check("error limpia busy", busy() === false, String(busy()));

// --- SSE: estado desconocido ---
applyTiaState({ state: "basura" });
check("estado desconocido se descarta", estado() === "error", estado());

// --- SSE: payload vacio o invalido ---
applyTiaState(null);
applyTiaState(undefined);
applyTiaState({});
applyTiaState({ state: "" });
check("payload invalido no rompe", estado() === "error", estado());
check("payload invalido conserva busy", busy() === false, String(busy()));

// --- Invariante: el estado siempre es uno de los 4 estables ---
check("estado dentro de los estables", ESTABLES.includes(estado()), estado());

// --- Snapshot HTTP ---
function stubFetch(payload) {
    return async () => ({
        ok: true,
        status: 200,
        headers: { get: () => null },
        json: async () => payload,
    });
}

globalThis.fetch = stubFetch({
    state: "connected",
    plcs: [],
    worker_alive: true,
});
await connectTia();
check("el snapshot aplica connected", estado() === "connected", estado());
check("el snapshot limpia busy", busy() === false, String(busy()));

// Un snapshot transitorio no puede dejar el estado fuera del
// contrato: el estado estable se conserva y solo se mueve ``busy``.
globalThis.fetch = stubFetch({
    state: "busy",
    plcs: [],
    worker_alive: true,
});
await connectTia();
check("el snapshot busy no deja state=busy", estado() !== "busy", estado());
check("el snapshot busy activa busy", busy() === true, String(busy()));
check("el snapshot busy deja un estado estable", ESTABLES.includes(estado()), estado());

// --- Invariante final ---
check("estado final estable", ESTABLES.includes(estado()), estado());

if (fallos > 0) {
    console.error("FALLOS: " + fallos);
    process.exit(1);
}
console.log("OK: contrato de estados TIA verificado");
"""


@pytest.mark.skipif(
    shutil.which("node") is None,
    reason="Node no esta disponible en este host",
)
def test_store_normaliza_los_estados_transitorios_del_worker_tia() -> None:
    """El store distingue "ocupado" de "desconectado".

    Reproduce el fallo que vaciaba el panel del editor de bloques
    tras un apply: el estado "busy" del worker se colaba en el store
    y el HMI lo leia como "no conectado".
    """
    import tempfile

    store_src = (JS_DIR / "store.js").read_text(encoding="utf-8")
    n_imports = store_src.count(VUE_IMPORT)
    assert n_imports == 1, (
        "Se esperaba exactamente 1 import de Vue en store.js (para "
        f"sustituirlo por el shim) y se encontraron {n_imports}. Si el "
        "import cambio, actualiza este test."
    )

    api_src = (JS_DIR / "api.js").read_text(encoding="utf-8")

    with tempfile.TemporaryDirectory(prefix="zc_spa_tia_") as tmp:
        tmpdir = Path(tmp)
        (tmpdir / "package.json").write_text(
            json.dumps({"type": "module"}), encoding="utf-8"
        )
        (tmpdir / "vue-shim.js").write_text(VUE_SHIM, encoding="utf-8")
        (tmpdir / "store.js").write_text(
            store_src.replace(
                VUE_IMPORT, 'import { reactive } from "./vue-shim.js";'
            ),
            encoding="utf-8",
        )
        (tmpdir / "api.js").write_text(api_src, encoding="utf-8")
        (tmpdir / "driver.js").write_text(DRIVER, encoding="utf-8")

        proc = subprocess.run(
            ["node", str(tmpdir / "driver.js")],
            capture_output=True,
            text=True,
            timeout=120,
        )

    assert proc.returncode == 0, (
        "El driver de Node fallo (contrato de estados TIA roto):\n"
        f"stdout:\n{proc.stdout}\n"
        f"stderr:\n{proc.stderr}"
    )
    assert "OK: contrato de estados TIA verificado" in proc.stdout, (
        f"stdout inesperado:\n{proc.stdout}\n"
        f"stderr:\n{proc.stderr}"
    )
