"""areas.alimentacion.data.data_Dimensiones — Data Block de N_MAX de dispositivos.

Fase 3, paso 3.2.2 (subdivision del plan original: ``data_Dispositivos.py``
se parte en dos archivos para mantener < 200 lineas).  Migrado de
``areas/alimentacion/domain/models/excel_cache.py`` (donde vivia como
``DimensionesDispositivos``).

Este archivo contiene SOLO ``DimensionesDispositivos`` (cantidades N_MAX
de los 6 tipos legacy + extras).  El legacy sigue coexistiendo (DA-006)
hasta Fase 4 (4.0.2: borrar ``areas/alimentacion/domain/``).

Convencion:
  - ``frozen=True``: las dimensiones N_MAX son casi inmutables; cambiar
    un N_MAX obliga a reescribir el dataclass completo.
  - Sin I/O, sin imports de ``siemens_tia_scripting`` u openpyxl.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


# Tabla canonica ``(hw_type, attr_legacy, nmax_name)`` para los 6 tipos.
_LEGACY_HW_TO_NMAX: tuple[tuple[str, str, str], ...] = (
    ("ed",    "num_disp_ed",   "N_MAX_DISP_ED"),
    ("ea",    "num_disp_ea",   "N_MAX_DISP_EA"),
    ("sa",    "num_disp_sa",   "N_MAX_DISP_SA"),
    ("v",     "num_disp_v",    "N_MAX_DISP_V"),
    ("m",     "num_disp_m",    "N_MAX_DISP_M"),
    ("m_vf",  "num_disp_m_vf", "N_MAX_DISP_M_VF"),
)


@dataclass(frozen=True)
class DimensionesDispositivos:
    """Cantidades numericas de dispositivos por tipo.

    Diseno extensible (data-driven):
      - Los 6 tipos canonicos (``ed/ea/sa/v/m/m_vf``) se exponen como
        campos explicitos ``num_disp_*`` para preservar la API legacy
        y los tests que construyen el dataclass por kwargs.
      - ``extras: dict[str, int]`` almacena N_MAX adicionales del
        ``n_max_catalog`` del config.
      - ``values()`` aplana los 6 legacy en ``{nombre_nmax: valor}``.
      - ``all_nmax()`` une ``values()`` con ``extras``.
      - ``to_api_dict()`` devuelve solo los 6 legacy para la API
        publica (SPA, diagnostics).
      - ``get(nmax_name)`` lee por nombre canonico o legacy.
      - ``from_catalog(catalog, raw)`` construye desde el
        ``ConfigManager`` y un dict raw del Excel.
    """

    num_disp_ed: int = 0
    num_disp_ea: int = 0
    num_disp_sa: int = 0
    num_disp_v: int = 0
    num_disp_m: int = 0
    num_disp_m_vf: int = 0
    # N_MAX adicionales del ``n_max_catalog`` del config.
    extras: Mapping[str, int] = field(default_factory=dict)

    def values(self) -> dict[str, int]:
        """``{nombre_nmax: valor}`` para los 6 canonicos (sin extras)."""
        result: dict[str, int] = {}
        for _hw, attr, nmax_name in _LEGACY_HW_TO_NMAX:
            result[nmax_name] = int(getattr(self, attr) or 0)
        return result

    def all_nmax(self) -> dict[str, int]:
        """``values()`` unificado con ``extras`` (extras gana si colisiona)."""
        merged = self.values()
        for k, v in self.extras.items():
            merged[str(k)] = int(v)
        return merged

    def to_api_dict(self) -> dict[str, int]:
        """Serializacion para la API publica: solo los 6 legacy."""
        return {
            attr: int(getattr(self, attr) or 0)
            for _hw, attr, _nmax in _LEGACY_HW_TO_NMAX
        }

    def get(self, nmax_name: str) -> int | None:
        """Lee por nombre canonico (``N_MAX_DISP_*``) o legacy (``num_disp_*``).

        ``None`` si no existe.
        """
        for _hw, attr, nmax in _LEGACY_HW_TO_NMAX:
            if nmax_name == nmax or nmax_name == attr:
                return int(getattr(self, attr) or 0)
        if nmax_name in self.extras:
            return int(self.extras[nmax_name])
        return None

    @classmethod
    def from_catalog(
        cls,
        catalog: list[dict] | None,
        raw: Mapping[str, int] | None,
    ) -> "DimensionesDispositivos":
        """Construye desde el ``n_max_catalog`` del ConfigManager y un raw.

        Politica:
          - Si el catalogo esta vacio o ``None``, acepta el raw tal
            cual: las claves que coincidan con los nombres legacy van
            a su campo; el resto va a ``extras``.
          - Si el catalogo esta presente, las claves del raw que NO
            esten en el catalogo se descartan (defensa contra typos).
        """
        raw = dict(raw or {})
        catalog_names: set[str] = set()
        if catalog:
            for entry in catalog:
                name = str(entry.get("name", "")).strip()
                hw = str(entry.get("hw_type", "")).strip()
                if name:
                    catalog_names.add(name)
                if hw:
                    for _h, _attr, nmax in _LEGACY_HW_TO_NMAX:
                        if _h == hw:
                            catalog_names.add(nmax)
                            break

        # 1. Rellenar los 6 campos legacy desde raw.
        kwargs: dict = {}
        for _hw, attr, nmax in _LEGACY_HW_TO_NMAX:
            v: int | None = None
            if nmax in raw:
                v = int(raw[nmax])
            elif attr in raw:
                v = int(raw[attr])
            if v is not None:
                kwargs[attr] = v

        # 2. El resto van a ``extras``. Si hay catalogo, las claves
        # no listadas se descartan.
        legacy_nmax_names = {nmax for _hw, _attr, nmax in _LEGACY_HW_TO_NMAX}
        extras: dict[str, int] = {}
        for k, v in raw.items():
            if k in legacy_nmax_names:
                continue
            if catalog and k not in catalog_names:
                continue
            try:
                extras[str(k)] = int(v)
            except (TypeError, ValueError):
                continue

        return cls(extras=extras, **kwargs)


__all__ = ["DimensionesDispositivos"]
