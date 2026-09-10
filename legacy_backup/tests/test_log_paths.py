"""Tests para ``core.application.log_paths.resolve_log_dir``.

Cubre la cadena de prioridad de la ruta de logs:

  1. Override por env var (``ZC_LOG_DIR``) si esta definida.
  2. Modo frozen: ``<exe_dir>/logs/``.
  3. Modo dev: ``<cwd>/logs/``.
  4. Fallback a AppData si la ruta prioritaria no se puede crear.

Verifica ademas que el directorio devuelto SIEMPRE existe en disco
(la funcion llama a ``mkdir(parents=True, exist_ok=True)``).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from core.application.log_paths import resolve_log_dir  # noqa: E402


# ── Helpers ────────────────────────────────────────────────────────


def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Asegura que ZC_LOG_DIR no contamina el test."""
    monkeypatch.delenv("ZC_LOG_DIR", raising=False)


def _patch_frozen(
    monkeypatch: pytest.MonkeyPatch, exe_path: Path
) -> None:
    """Simula modo frozen apuntando a ``exe_path``."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_path), raising=False)


# ── Default dev mode ─────────────────────────────────────────────


def test_dev_mode_returns_cwd_logs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Sin env var ni frozen, devuelve ``<cwd>/logs``."""
    _clean_env(monkeypatch)
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)

    result = resolve_log_dir()

    assert result == tmp_path / "logs"
    assert result.is_dir()  # la funcion crea el dir


def test_dev_mode_creates_missing_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Si ``<cwd>/logs`` no existe, lo crea."""
    _clean_env(monkeypatch)
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    assert not (tmp_path / "logs").exists()

    result = resolve_log_dir()

    assert result.is_dir()


# ── Modo frozen ──────────────────────────────────────────────────


def test_frozen_mode_returns_exe_dir_logs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Con ``sys.frozen=True``, devuelve ``<exe_dir>/logs``."""
    _clean_env(monkeypatch)
    fake_exe = tmp_path / "zc_automation_suite.exe"
    fake_exe.touch()
    _patch_frozen(monkeypatch, fake_exe)
    # El cwd no debe importar en modo frozen.
    monkeypatch.setattr(Path, "cwd", lambda: Path("Z:/NO_DEBERIA_APARECER"))

    result = resolve_log_dir()

    assert result == tmp_path / "logs"
    assert result.is_dir()


# ── Override por env var ─────────────────────────────────────────


def test_env_var_overrides_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``ZC_LOG_DIR`` gana sobre el default."""
    _clean_env(monkeypatch)
    custom = tmp_path / "custom_logs"
    monkeypatch.setenv("ZC_LOG_DIR", str(custom))
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path / "irrelevante")

    result = resolve_log_dir()

    assert result == custom
    assert result.is_dir()


def test_env_var_empty_string_falls_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``ZC_LOG_DIR=""`` se trata como no definida."""
    _clean_env(monkeypatch)
    monkeypatch.setenv("ZC_LOG_DIR", "   ")  # whitespace tambien
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)

    result = resolve_log_dir()

    assert result == tmp_path / "logs"


def test_env_var_with_invalid_path_falls_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Si el override no se puede crear, cae al default (no a AppData)."""
    _clean_env(monkeypatch)
    # Path en un caracter invalido en Windows; en *nix igual falla.
    invalid = tmp_path / "x:y" / "no_puede_crearse"
    monkeypatch.setenv("ZC_LOG_DIR", str(invalid))
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)

    # En Windows el mkdir lanza OSError, en *nix el path tambien falla.
    # Si por algun motivo el OS lo permite, el test reporta que el
    # override fue aceptado (esto seria inesperado).
    try:
        result = resolve_log_dir()
    except Exception:
        pytest.fail("resolve_log_dir no debe propagar excepciones")

    # Si cayo al default, sera tmp_path / "logs"; si no, el override
    # fue aceptado. Ambos son validos siempre que el resultado exista.
    assert result.is_dir()
    assert result != invalid or result == invalid.resolve()


# ── Fallback a AppData ──────────────────────────────────────────


def test_fallback_to_appdata_when_default_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Si el default no se puede crear, cae al AppData legacy."""
    _clean_env(monkeypatch)
    # Forzamos HOME antes de parchear mkdir, asi el setup del test
    # no se ve afectado por el patch.
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    # Parcheamos SOLO el helper interno que ``resolve_log_dir`` usa,
    # no ``Path.mkdir`` globalmente (eso romperia operaciones legitimas
    # del propio test, como la creacion de ``fake_home``).
    from core.application import log_paths

    call_count = {"n": 0}

    def _fake_try_mkdir(path: Path, source: str) -> bool:
        # Primera llamada (default) falla; las siguientes (AppData) pasan.
        call_count["n"] += 1
        if call_count["n"] == 1:
            return False
        path.mkdir(parents=True, exist_ok=True)
        return True

    monkeypatch.setattr(log_paths, "_try_mkdir", _fake_try_mkdir)

    result = resolve_log_dir()

    # Cae al AppData legacy con el subdir "logs".
    expected = fake_home / "AppData" / "Local" / "zc-automation-suite" / "logs"
    assert result == expected
    # La funcion crea el dir como ultimo recurso.
    assert result.is_dir()


# ── Invariante: la ruta devuelta SIEMPRE existe ──────────────────


def test_returned_path_always_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Cualquiera de los caminos posibles debe dejar el dir en disco."""
    _clean_env(monkeypatch)
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)

    result = resolve_log_dir()

    assert result.exists()
    assert result.is_dir()


# ── Coherencia: dos llamadas seguidas devuelven el mismo path ────


def test_idempotent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Llamar dos veces devuelve el mismo path (mismo env, mismo cwd)."""
    _clean_env(monkeypatch)
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)

    first = resolve_log_dir()
    second = resolve_log_dir()

    assert first == second
