"""Tests del resolver de paths de ``config.json`` (frozen/dev/override).

Cubre los 6 escenarios del diseño:

  1. Modo dev: ``resolve_config_path()`` devuelve ``<cwd>/infrastructure/config.json``.
  2. Modo frozen + usuario ya tiene config: devuelve el del usuario
     (NO sobreescribe, aunque el bundleado sea "mas nuevo").
  3. Modo frozen + primera ejecucion: copia el bundleado a
     ``<exe_dir>/config/config.json`` y lo devuelve.
  4. Modo frozen + no se puede escribir: fallback readonly al
     bundleado con warning.
  5. Override por env var ``ZC_CONFIG_DIR``: usa esa ruta; si no
     existe, copia el bundleado alli.
  6. El usuario gana siempre: aunque el bundleado cambie entre
     llamadas, el del usuario NO se reescribe.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.infrastructure import config_paths
from core.infrastructure.config_paths import resolve_config_path


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_bundled(
    meipass: Path, content: str = '{"_bundled": true, "version": 1}',
) -> Path:
    """Crea un config.json bundleado en ``<meipass>/infrastructure/``."""
    bundled_dir = meipass / "infrastructure"
    bundled_dir.mkdir(parents=True, exist_ok=True)
    bundled = bundled_dir / "config.json"
    bundled.write_text(content, encoding="utf-8")
    return bundled


def _set_frozen(
    monkeypatch: pytest.MonkeyPatch, meipass: Path | None,
    exe_dir: Path | None = None,
) -> None:
    """Configura ``sys.frozen``, ``sys._MEIPASS`` y ``sys.executable``
    para simular PyInstaller. ``exe_dir`` controla donde cree el
    resolver que esta el ``.exe`` (y por tanto donde escribe
    ``<exe_dir>/config/config.json``)."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    if meipass is not None:
        monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)
    if exe_dir is not None:
        fake_exe = exe_dir / "zc_automation_suite.exe"
        monkeypatch.setattr(sys, "executable", str(fake_exe), raising=False)


def _clear_frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    """Quita los atributos frozen (modo dev)."""
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)


# ── 1. Modo dev ──────────────────────────────────────────────────────────


def test_dev_mode_devuelve_path_del_repo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """En dev (``sys.frozen`` False), devuelve ``<cwd>/infrastructure/config.json``.

    No se copia nada: el developer edita el archivo en su repo
    directamente.
    """
    _clear_frozen(monkeypatch)
    monkeypatch.chdir(tmp_path)
    # El repo ficticio tiene el config.json bundleado en CWD.
    _make_bundled(tmp_path)

    result = resolve_config_path()

    assert result == tmp_path / "infrastructure" / "config.json"
    assert result.is_file()
    # No se crea una copia en <cwd>/config/ (eso es solo frozen).
    assert not (tmp_path / "config" / "config.json").exists()


# ── 2. Modo frozen + usuario ya tiene config ─────────────────────────────


def test_frozen_existing_user_config_wins(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """En frozen, si el usuario ya tiene ``<exe_dir>/config/config.json``,
    se usa ESA (no se sobreescribe con el bundleado, aunque el
    bundleado sea "mas nuevo").
    """
    meipass = tmp_path / "meipass"
    exe_dir = tmp_path / "exe"
    exe_dir.mkdir(parents=True)
    user_config = exe_dir / "config" / "config.json"
    user_config.parent.mkdir(parents=True)
    user_config.write_text('{"_user": true, "version": 99}', encoding="utf-8")
    _make_bundled(meipass, content='{"_bundled": true, "version": 1}')
    _set_frozen(monkeypatch, meipass, exe_dir)
    monkeypatch.setattr(config_paths, "_logger", MagicMock())

    result = resolve_config_path()

    assert result == user_config
    # Contenido del USUARIO, no del bundleado.
    assert '"_user": true' in result.read_text(encoding="utf-8")
    assert '"_bundled": true' not in result.read_text(encoding="utf-8")


# ── 3. Modo frozen + primera ejecucion (copia) ───────────────────────────


def test_frozen_first_run_copia_bundled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """En frozen, si ``<exe_dir>/config/config.json`` NO existe, se
    copia el bundleado y se devuelve la nueva ruta. Loggea info
    notificando la creacion.
    """
    meipass = tmp_path / "meipass"
    exe_dir = tmp_path / "exe"
    exe_dir.mkdir(parents=True)
    _make_bundled(meipass, content='{"_bundled": true, "version": 1}')
    _set_frozen(monkeypatch, meipass, exe_dir)

    expected_dst = exe_dir / "config" / "config.json"
    assert not expected_dst.exists()  # precondicion: no existe

    with caplog.at_level(logging.INFO, logger="core.infrastructure.config_paths"):
        result = resolve_config_path()

    assert result == expected_dst
    assert result.is_file()
    assert '"_bundled": true' in result.read_text(encoding="utf-8")
    assert any("Se creo" in r.message for r in caplog.records), (
        f"Se esperaba log 'Se creo...', se emitio: "
        f"{[r.message for r in caplog.records]}"
    )


# ── 4. Modo frozen + no se puede escribir (fallback readonly) ────────────


def test_frozen_no_se_puede_escribir_fallback_readonly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Si ``<exe_dir>/config/`` no es escribible, fallback al
    bundleado directo con warning.
    """
    meipass = tmp_path / "meipass"
    exe_dir = tmp_path / "exe"
    exe_dir.mkdir(parents=True)
    bundled = _make_bundled(meipass, content='{"_bundled": true}')
    _set_frozen(monkeypatch, meipass, exe_dir)

    # Forzar OSError al hacer ``mkdir`` de ``<exe_dir>/config/``.
    real_mkdir = Path.mkdir
    def fake_mkdir(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        if self == exe_dir / "config":
            raise OSError(13, "Permission denied (simulado)")
        return real_mkdir(self, *args, **kwargs)
    monkeypatch.setattr(Path, "mkdir", fake_mkdir)

    with caplog.at_level(logging.WARNING, logger="core.infrastructure.config_paths"):
        result = resolve_config_path()

    # Fallback: devuelve la ruta bundleada.
    assert result == bundled
    assert any("readonly" in r.message or "permisos" in r.message
               for r in caplog.records), (
        f"Se esperaba warning de fallback, se emitio: "
        f"{[r.message for r in caplog.records]}"
    )


# ── 5. Override por env var ZC_CONFIG_DIR ────────────────────────────────


def test_env_var_override_usa_path_y_copia(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Si ``$ZC_CONFIG_DIR`` está definido, se usa esa ruta. Si el
    archivo no existe alli, se copia el bundleado (primera ejecucion).
    """
    meipass = tmp_path / "meipass"
    _make_bundled(meipass, content='{"_bundled": true}')
    # En este test el env var toma prioridad sobre frozen; no hace
    # falta mockear ``sys.executable`` (no se consulta).
    _set_frozen(monkeypatch, meipass, exe_dir=tmp_path / "exe_unused")

    override_dir = tmp_path / "custom_config_dir"
    monkeypatch.setenv("ZC_CONFIG_DIR", str(override_dir))
    expected_dst = override_dir / "config.json"
    assert not expected_dst.exists()  # precondicion

    with caplog.at_level(logging.INFO, logger="core.infrastructure.config_paths"):
        result = resolve_config_path()

    assert result == expected_dst
    assert result.is_file()
    assert any("Se creo" in r.message for r in caplog.records)


def test_env_var_override_con_archivo_preexistente(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Si ``$ZC_CONFIG_DIR`` apunta a un dir con config.json, se usa
    esa version (no se sobreescribe con el bundleado).
    """
    meipass = tmp_path / "meipass"
    _make_bundled(meipass, content='{"_bundled": true, "v": 1}')
    _set_frozen(monkeypatch, meipass, exe_dir=tmp_path / "exe_unused")

    override_dir = tmp_path / "custom_config_dir"
    override_dir.mkdir(parents=True)
    user_cfg = override_dir / "config.json"
    user_cfg.write_text('{"_user": true, "v": 99}', encoding="utf-8")
    monkeypatch.setenv("ZC_CONFIG_DIR", str(override_dir))

    result = resolve_config_path()

    assert result == user_cfg
    assert '"_user": true' in result.read_text(encoding="utf-8")
    assert '"_bundled": true' not in result.read_text(encoding="utf-8")


# ── 6. El usuario gana siempre (segunda llamada no reescribe) ────────────


def test_segunda_llamada_no_reescribe_usuario(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Tras la primera copia, las llamadas siguientes NO tocan el
    archivo del usuario aunque el bundleado "cambie" entre medias.
    El operario puede estar editando tranquilamente.
    """
    meipass = tmp_path / "meipass"
    exe_dir = tmp_path / "exe"
    exe_dir.mkdir(parents=True)
    _make_bundled(meipass, content='{"_bundled_v1": true}')
    _set_frozen(monkeypatch, meipass, exe_dir)

    # Primera llamada: copia el bundleado v1.
    first = resolve_config_path()
    assert '"_bundled_v1": true' in first.read_text(encoding="utf-8")

    # El operario edita.
    first.write_text('{"_user_edit": "mi config"}', encoding="utf-8")

    # El "desarrollador" actualiza el bundleado (v2).
    (meipass / "infrastructure" / "config.json").write_text(
        '{"_bundled_v2": true}', encoding="utf-8"
    )

    # Segunda llamada: NO debe pisar la edicion del operario.
    second = resolve_config_path()
    assert second == first
    assert '"_user_edit"' in second.read_text(encoding="utf-8")
    assert '"_bundled_v2"' not in second.read_text(encoding="utf-8")
