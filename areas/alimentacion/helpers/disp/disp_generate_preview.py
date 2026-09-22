"""areas.alimentacion.helpers.disp.disp_generate_preview - funciones puras de diff.

Funciones puras data-driven que comparan la lista de dispositivos
deseados (Excel del operario) contra el XML exportado de TIA Portal.

Refactor sept-2026: la antigua version de este archivo era un
orquestador con state machine (``exportar_tags`` + ``compute_devices``
+ ``compute_nmax`` + ``build_response``) que recibia un
``DispPreviewContext`` y lo mutaba. Esa logica se movio a los FBs
(``function_disp_generar_preview._stage_N_*``) y al final se quedo
un duplicado del codigo que nadie llamaba. Este archivo fue
sobrescrito en sept-2026 con dos funciones puras, reutilizables y
testables sin mocks de AppState/config_manager/Context.

Convenio de uso (sept-2026, ``_plan/rutas.md``):

  - El FB ``FunctionDispGenerarPreview`` invoca
    ``compute_diff_table(table_name, devices, xml_path)`` por cada
    hw_type (6 veces en ciclo de disp).
  - El FB invoca ``compute_nmax_diff(desired_nmax, xml_path)`` una
    sola vez para las N_MAX.

Restricciones arquitectonicas:
  - Sin imports de ``siemens_tia_scripting``.
  - Sin Singletons. Sin acceso a AppState ni config_manager.
  - El caller (FB) construye el ``desired_devices`` y el
    ``desired_nmax`` y los pasa por argumento; aqui solo se hace el
    diff puro contra el XML.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from core.helpers.simatic_ml import PlcUserConstantModifier, PlcUserConstantParser

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Protocols (no atan al area; cualquier objeto con estos atributos sirve)
# ---------------------------------------------------------------------------


class DispositivoLike(Protocol):
    """Contrato minimo de un dispositivo del Excel.

    Lo que necesitamos para el diff es solo ``numero`` (uid en TIA) y
    ``plc_tag`` (el nombre humano en TIA). El resto del modelo
    (descripcion, plc_comentario, ...) no afecta al diff.
    """

    numero: int
    plc_tag: str


# ---------------------------------------------------------------------------
# Dataclass de salida: DiffTable (devices)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DiffTable:
    """Resultado del diff entre desired (Excel) y base (TIA) para 1 tabla.

    Atributos:
        table_name: nombre de la tabla TIA (e.g. ``"2000_Disp_ED"``).
            Solo para logs/debug; no se usa en el diff.
        base: ``{uid_str: plc_tag}`` del TIA (``PlcTagTable`` exportada).
            Vacio si el XML no existia (``missing_xml=True``).
        desired: ``{uid_str: plc_tag}`` del Excel (los disp que quiere
            el operario). Vacio si el operario no tiene disp de este
            tipo en el Excel.
        added: lista de uids en ``desired`` pero NO en ``base``
            (disp que el operario quiere agregar a TIA).
        removed: lista de uids en ``base`` pero NO en ``desired``
            (disp que el operario quiere eliminar de TIA).
        renamed: ``{uid_str: (plc_tag_TIA, plc_tag_Excel)}`` para
            uids presentes en ambos pero con plc_tag distinto.
        missing_xml: ``True`` si el XML de TIA no existia en disco.
            En ese caso, ``base={}`` y TODOS los desired aparecen en
            ``added``. El operario ve el warning y puede decidir si
            continuar (es ambiguo: el XML no existe, no sabemos si TIA
            tiene esos disp o no).
    """

    table_name: str
    base: dict[str, str]
    desired: dict[str, str]
    added: list[str]
    removed: list[str]
    renamed: dict[str, tuple[str, str]]
    missing_xml: bool = False

    @property
    def is_empty(self) -> bool:
        """True si no hay ningun cambio (desired == base)."""
        return not (self.added or self.removed or self.renamed)

    @property
    def n_total_changes(self) -> int:
        """Total de entradas a aplicar en TIA (added + renamed)."""
        return len(self.added) + len(self.renamed)


# ---------------------------------------------------------------------------
# Dataclass de salida: NmaxDiff (N_MAX, valores numericos)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NmaxDiff:
    """Resultado del diff de N_MAX entre desired (Excel) y base (TIA).

    A diferencia de ``DiffTable`` (devices), las N_MAX son
    PlcUserConstant que **siempre existen** en TIA: no se crean ni se
    eliminan, solo se modifica su valor. Por eso el shape del diff
    aqui es diferente:

      - ``current``: valores del TIA (``{nombre_nmax: valor}``).
      - ``desired``: valores del Excel (``{nombre_nmax: valor}``).
      - ``todos``: lista de ``{name, actual, nuevo, status}`` (uno por
        cada nombre en ``list_nmax_active``). El caller filtra/ordena
        para la SPA.
      - ``summary``: ``{actualizar, sin_cambios, total}``.
      - ``missing_xml``: True si el XML no existia (modo degradado).

    Atributos:
        table_name: nombre de la tabla N_MAX (``"000_Config_Dispositivos"``).
        current: valores del TIA (puede ser ``{}`` si XML falta).
        desired: valores del Excel.
        todos: lista de entries individuales para el preview.
        summary: contadores.
        missing_xml: True si el XML no existia.
    """

    table_name: str
    current: dict[str, int]
    desired: dict[str, int]
    todos: list[dict[str, Any]]
    summary: dict[str, int]
    missing_xml: bool = False


# ---------------------------------------------------------------------------
# Helpers privados (lectura XML)
# ---------------------------------------------------------------------------


def _read_devices_from_xml(xml_path: Path) -> dict[str, str]:
    """Lee un XML FLAT de ``PlcTagTable`` y devuelve ``{uid_str: plc_tag}``.

    Shape: el ``<Value>`` del PlcUserConstant es el uid numerico (clave);
    el ``<Name>`` es el plc_tag (valor). Filtra constantes no
    casteables a int (consistente con el parser).

    Args:
        xml_path: ruta al .xml exportado por ``export_tag_table`` o
            ``export_plc_tags_xml`` con ``keep_folder_structure=False``
            (preview FLAT).

    Returns:
        Dict ``{uid_str: plc_tag}``. Vacio si el archivo no existe o
        no se pudo parsear (los warnings se loguean desde el caller).
    """
    if not xml_path.is_file():
        return {}
    try:
        modifier = PlcUserConstantModifier(xml_path)
    except Exception as exc:
        logger.warning(
            f"[diff] No se pudo cargar XML de disp '{xml_path.name}': {exc}"
        )
        return {}
    return dict(modifier.read_user_constants_with_uids())


def _read_nmax_from_xml(xml_path: Path) -> tuple[dict[str, int], str | None]:
    """Lee un XML FLAT de ``PlcTagTable`` con N_MAX y devuelve ``{name: value}``.

    Shape: ``<Name>`` es el nombre del N_MAX (clave), ``<Value>`` es el
    valor entero. Solo incluye casteables a int (constantes Real/String
    se descartan automaticamente).

    Args:
        xml_path: ruta al .xml de la tabla N_MAX
            (``preview_config/000_Config_Dispositivos.xml``).

    Returns:
        Tupla ``(values_dict, error_message)``. ``values_dict`` es
        ``{}`` si el archivo no existe o fallo el parseo. ``error_message``
        es ``None`` si OK, o un string describiendo el fallo (que el
        caller rendera en la SPA para que el operario sepa que el diff
        de N_MAX puede estar incompleto).
    """
    if not xml_path.is_file():
        return {}, f"XML de N_MAX no encontrado en TIA export: {xml_path}"
    try:
        values = PlcUserConstantParser.parse_user_constants(xml_path)
        return dict(values), None
    except Exception as exc:
        logger.error(f"[N_MAX] Parse FAIL {xml_path}: {exc}")
        return {}, f"parse fail: {exc}"


# ---------------------------------------------------------------------------
# API publica: compute_diff_table (devices)
# ---------------------------------------------------------------------------


def compute_diff_table(
    table_name: str,
    desired_devices: list[DispositivoLike],
    xml_path: Path,
) -> DiffTable:
    """Calcula el diff entre desired_devices (Excel) y xml_path (TIA).

    Funcion pura, sin AppState/config_manager. Se puede llamar 1 vez
    por hw_type (6 en ciclo de disp) o N veces en tests con mocks.

    Args:
        table_name: nombre de la tabla TIA (e.g. ``"2000_Disp_ED"``).
            Solo se usa en el campo ``table_name`` del resultado, no
            afecta al calculo del diff. Si pasas ``""`` se asume que
            quieres el diff anonimo (util en tests).
        desired_devices: lista de ``DispositivoLike`` (Excel). Acepta
            cualquier objeto con atributos ``.numero`` (int) y
            ``.plc_tag`` (str). Si vacia, todos los disp de TIA
            aparecen como ``removed``.
        xml_path: ruta al ``.xml`` FLAT exportado de TIA. Si no
            existe, devuelve ``DiffTable(missing_xml=True)`` con
            ``base={}`` y todos los desired como ``added``.

    Returns:
        ``DiffTable`` con los 4 vectores del diff + ``base`` para
        debug. Ver ``DiffTable`` para el detalle de campos.

    Examples:
        >>> from pathlib import Path
        >>> diff = compute_diff_table(
        ...     "2000_Disp_ED",
        ...     desired_devices=[FakeDevice(numero=1, plc_tag="ED_001")],
        ...     xml_path=Path("preview_disp/2000_Disp_ED.xml"),
        ... )
        >>> diff.added
        []
        >>> diff.removed
        []
        >>> diff.is_empty
        True
    """
    # 1. Parse desired: ``{uid_str: plc_tag}``.
    desired: dict[str, str] = {}
    for device in desired_devices:
        numero = int(getattr(device, "numero", 0) or 0)
        plc_tag = str(getattr(device, "plc_tag", "") or "")
        if numero > 0 and plc_tag:
            desired[str(numero)] = plc_tag

    # 2. Parse base desde el XML de TIA.
    base = _read_devices_from_xml(xml_path)
    missing_xml = not xml_path.is_file()

    # 3. Calcula los 3 vectores del diff.
    base_uids = set(base.keys())
    desired_uids = set(desired.keys())

    added = sorted(desired_uids - base_uids)
    removed = sorted(base_uids - desired_uids)
    renamed: dict[str, tuple[str, str]] = {
        uid: (base[uid], desired[uid])
        for uid in (base_uids & desired_uids)
        if base[uid] != desired[uid]
    }

    return DiffTable(
        table_name=table_name,
        base=base,
        desired=desired,
        added=added,
        removed=removed,
        renamed=renamed,
        missing_xml=missing_xml,
    )


# ---------------------------------------------------------------------------
# API publica: compute_nmax_diff (N_MAX)
# ---------------------------------------------------------------------------


def compute_nmax_diff(
    table_name: str,
    desired_nmax: dict[str, int],
    xml_path: Path,
) -> NmaxDiff:
    """Calcula el diff de N_MAX entre desired_nmax (Excel) y xml_path (TIA).

    A diferencia de devices, las N_MAX **siempre existen** en TIA: no se
    crean ni eliminan, solo se modifica su valor. Por eso el diff aqui
    itera sobre las **keys de desired_nmax** (que es la lista canonica
    de N_MAX activas del config) y compara cada una contra el current
    de TIA.

    Args:
        table_name: nombre de la tabla N_MAX
            (``"000_Config_Dispositivos"``).
        desired_nmax: ``{nombre_nmax: valor_deseado}`` del Excel. Suele
            venir de ``DimensionesDispositivos.values()`` o equivalente.
            Si una key no esta en el XML de TIA, ``current[nombre]``
            sera ``None`` y el status sera ``"actualizar"``.
        xml_path: ruta al XML FLAT de TIA con las N_MAX
            (``preview_config/000_Config_Dispositivos.xml``).

    Returns:
        ``NmaxDiff`` con ``current``/``desired``/``todos``/``summary``
        para que la SPA renderice la card "30 → 0".

    Examples:
        >>> diff = compute_nmax_diff(
        ...     "000_Config_Dispositivos",
        ...     desired_nmax={"N_MAX_DISP_ED": 50, "N_MAX_DISP_EA": 50},
        ...     xml_path=Path("preview_config/000_Config_Dispositivos.xml"),
        ... )
        >>> diff.summary["actualizar"]
        2
    """
    current, error_message = _read_nmax_from_xml(xml_path)
    missing_xml = error_message is not None

    # Si el XML fallo, devolvemos todos=[] para que la SPA muestre el
    # error y no proponga diffs contra current={} (que marcaria TODO
    # como actualizar).
    if missing_xml:
        return NmaxDiff(
            table_name=table_name,
            current={},
            desired=dict(desired_nmax),
            todos=[],
            summary={
                "actualizar": 0,
                "sin_cambios": len(desired_nmax),
                "total": len(desired_nmax),
            },
            missing_xml=True,
        )

    # Calcula los todos contra ``desired_nmax`` (no contra ``current``):
    # asi detectamos N_MAX que el operario quiere bajar a 0 (que en TIA
    # estan como 30 pero el Excel dice 0 -> "actualizar").
    todos: list[dict[str, Any]] = []
    for name in desired_nmax.keys():
        cur_val = current.get(name)
        des_val = int(desired_nmax[name])
        if cur_val is not None and int(cur_val) == des_val:
            status = "sin_cambios"
        else:
            status = "actualizar"
        todos.append({
            "name": name,
            "actual": cur_val,
            "nuevo": des_val,
            "status": status,
        })

    return NmaxDiff(
        table_name=table_name,
        current=current,
        desired=dict(desired_nmax),
        todos=todos,
        summary={
            "actualizar": sum(1 for r in todos if r["status"] == "actualizar"),
            "sin_cambios": sum(1 for r in todos if r["status"] == "sin_cambios"),
            "total": len(todos),
        },
        missing_xml=False,
    )


__all__ = [
    "DispositivoLike",
    "DiffTable",
    "NmaxDiff",
    "compute_diff_table",
    "compute_nmax_diff",
]
