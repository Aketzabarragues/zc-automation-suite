"""Conftest raiz para zc-automation-suite.

Anade la raiz del proyecto al ``sys.path`` para que los tests puedan
hacer ``from core.web.app import app``. Pytest deberia hacerlo solo con
``pythonpath = .`` en pytest.ini o pyproject.toml, pero en pytest 9.x
hay un bug conocido donde no se aplica si ambos config files coexisten.

Workaround: anyadir manualmente al sys.path aqui, antes de cualquier
import. El conftest se ejecuta antes de cualquier test.
"""
from __future__ import annotations

import sys
from pathlib import Path

_RAIZ = Path(__file__).resolve().parent
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))
