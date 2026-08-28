"""Orquestador de procesos IT de comunicación con TIA Portal.

Garantiza la separación absoluta entre el proceso asíncrono principal (FastMCP)
y el runtime síncrono de Siemens. Maneja la caché de memoria IT y la invocación
de subprocess. Backend headless: sin UI propia.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any


# Timeout por defecto del subproceso OT (segundos).
#
# Una ``execute_transactional_batch`` contra un PLC real puede
# implicar 50-100 operaciones dentro de ``start_transaction`` /
# ``end_transaction``. Con PLCs reales esto puede tardar 1-3 minutos
# (ver `.clinerules` §1: el stage ``open_transaction`` es OPAQUE y
# cubre la transacción COM). El default histórico era 45s, que se
# quedaba corto y forzaba timeouts en operaciones grandes.
#
# Operario en producción: ajustar con la variable de entorno
# ``ZC_GATEWAY_TIMEOUT`` (segundos) sin recompilar. Tests que
# parcheen ``sys.frozen`` no se ven afectados — el valor de la
# env var se evalúa por instancia, en el ``__init__`` del gateway.
DEFAULT_GATEWAY_TIMEOUT: float = float(
    os.environ.get("ZC_GATEWAY_TIMEOUT", "300.0")
)


class TIAProcessGateway:
    """Gateway asíncrono hacia el motor OT mediante subprocesos efímeros.

    Resolución del subproceso:
      - Modo desarrollo: sys.executable es python.exe; se lanza
        'python -u main.py --worker' (main.py enruta al worker OT).
      - Modo empaquetado (PyInstaller --onefile): sys.frozen es True;
        sys.executable es zc_automation_suite.exe, que al recibir --worker
        enruta internamente al worker OT. En este modo los scripts .py
        NO existen físicamente (residen en el PYZ), por lo que NO se
        referencian rutas a .py.
    """

    def __init__(self, timeout: float | None = None) -> None:
        """Inicializa el gateway IT.

        Args:
            timeout: Timeout (segundos) del subproceso OT. Si es
                ``None`` (default), usa ``DEFAULT_GATEWAY_TIMEOUT``
                (180s, configurable vía ``ZC_GATEWAY_TIMEOUT``). Pasarlo
                explícito tiene prioridad sobre la env var (útil para
                tests con mocks que necesitan un timeout corto).
        """
        self._cache: dict[str, Any] = {}
        self._timeout = timeout if timeout is not None else DEFAULT_GATEWAY_TIMEOUT

    def _resolve_worker_exec_args(self) -> list[str]:
        """Devuelve los argumentos para lanzar el subproceso worker.

        La diferenciación frozen/dev se evalúa en cada llamada para
        robustez ante tests que parcheen sys.frozen en runtime.
        """
        if getattr(sys, "frozen", False):
            # Entorno de producción (PyInstaller --onefile):
            # sys.executable ES el binario compilado.
            return ["--worker"]

        # Entorno de desarrollo: invocar main.py con el intérprete actual.
        # ``main.py`` vive en la RAÍZ del repo, no dentro de ``core/``.
        # Este módulo está en ``core/infrastructure/gateway.py``:
        #   Path(__file__).parent            = core/infrastructure/
        #   Path(__file__).parent.parent      = core/
        #   Path(__file__).parent.parent.parent = <raíz>
        # (Antes de PR 1, el módulo estaba en ``infrastructure/gateway.py``
        # y bastaba con un solo ``..``. Tras PR 1 se movió un nivel más
        # abajo, hay que subir un nivel adicional.)
        main_script = Path(__file__).parent.parent.parent / "main.py"
        return ["-u", str(main_script), "--worker"]

    async def _dispatch_worker(
        self,
        command: str,
        args: dict[str, Any] | None = None,
        timeout_override: float | None = None,
    ) -> Any:
        """Lanza main.py (o el .exe congelado) con --worker y le envía el payload por STDIN.

        Args:
            command: Nombre del comando del COMMAND_REGISTRY del worker.
            args: Argumentos JSON-serializables para el comando.
            timeout_override: Si se pasa, se usa este timeout en lugar
                de ``self._timeout`` (útil para operaciones bulk como
                ``execute_transactional_batch`` que necesitan un timeout
                proporcional al número de operaciones). ``None``
                usa el default del gateway.
        """
        timeout = timeout_override if timeout_override is not None else self._timeout
        exec_args = self._resolve_worker_exec_args()

        # Forzar encoding UTF-8 en el subproceso (heredado del
        # padre). Sin esto, en Windows el worker arranca con
        # cp1252 y Pythonnet revienta al convertir strings de
        # TIA Portal (Latin-1) a Python UTF-8.
        import os as _os
        worker_env = {
            **_os.environ,
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
        }

        # Invocación: -u (unbuffered I/O) en desarrollo, solo --worker en frozen.
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            *exec_args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=worker_env,
        )

        payload_bytes = json.dumps({"command": command, "args": args or {}}).encode(
            "utf-8"
        )

        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(input=payload_bytes),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise RuntimeError(
                f"Timeout tras {timeout}s ejecutando el comando '{command}'. "
                "El subproceso OT no respondió (posible diálogo modal activo en TIA Portal)."
            )

        stderr_text = stderr_b.decode("utf-8", errors="replace").strip()
        stdout_text = stdout_b.decode("utf-8", errors="replace").strip()

        if proc.returncode != 0 and not stdout_text:
            raise RuntimeError(
                f"El subproceso OT colapsó (exit code {proc.returncode}). Error: {stderr_text or 'Sin salida'}"
            )

        # Extraer la última línea válida parseable como JSON (filtro contra interferencias)
        json_response = None
        for line in reversed(stdout_text.splitlines()):
            line_str = line.strip()
            if line_str.startswith("{") and line_str.endswith("}"):
                try:
                    json_response = json.loads(line_str)
                    break
                except json.JSONDecodeError:
                    continue

        if json_response is None:
            raise RuntimeError(
                f"Respuesta inválida del worker OT. STDOUT: '{stdout_text}' | STDERR: '{stderr_text}'"
            )

        if not json_response.get("ok"):
            # Incluir stderr del worker para diagnóstico (traceback
            # completo, mensajes de Pythonnet, etc.). Sin esto,
            # solo vemos el error resumido.
            err = json_response.get("error", "Error interno en el worker OT.")
            if stderr_text:
                raise RuntimeError(f"{err} | STDERR: {stderr_text[:2000]}")
            raise RuntimeError(err)

        return json_response.get("result")

    async def get_plcs(self, force_refresh: bool = False) -> list[str]:
        """Obtiene los PLCs disponibles utilizando la caché de memoria IT."""
        cache_key = "plcs"
        if not force_refresh and cache_key in self._cache:
            return self._cache[cache_key]

        plcs = await self._dispatch_worker("list_plcs")
        self._cache[cache_key] = plcs
        return plcs

    async def get_blocks(
        self, plc_name: str, folder_path: str | None = None, force_refresh: bool = False
    ) -> list[str]:
        """Obtiene los bloques de programa de un PLC con caché dirigida."""
        cache_key = f"blocks::{plc_name}::{folder_path or ''}"
        if not force_refresh and cache_key in self._cache:
            return self._cache[cache_key]

        blocks = await self._dispatch_worker(
            "list_blocks", {"plc_name": plc_name, "folder_path": folder_path}
        )
        self._cache[cache_key] = blocks
        return blocks

    def clear_cache(self) -> None:
        """Limpia el estado IT almacenado en memoria."""
        self._cache.clear()

    async def compile_plc(self, plc_name: str) -> bool:
        """Compila el software del PLC devolviendo el booleano nativo de Siemens.

        Semántica documentada (TIA Scripting API V1.2.1, sección 2.2.11):
          - True  -> La compilación tiene errores.
          - False -> La compilación NO tiene errores (éxito).
        La evaluación semántica para el usuario final ocurre en la capa MCP.
        """
        return await self._dispatch_worker(
            "compile_plc", {"plc_name": plc_name}
        )

    async def export_blocks_sd(self, plc_name: str, target_dir: str) -> str:
        """Exporta los bloques de programa del PLC a archivos Simatic Source Documents (.s7dcl) en target_dir.

        Fail-Fast: target_dir debe ser una ruta absoluta. No se almacena en caché
        porque es una acción mutable que vuelca contenido a disco.
        """
        if not Path(target_dir).is_absolute():
            raise ValueError(
                f"target_dir debe ser una ruta absoluta. Recibido: '{target_dir}'"
            )

        return await self._dispatch_worker(
            "export_blocks_sd",
            {"plc_name": plc_name, "target_dir": target_dir},
        )

    async def export_udts_sd(self, plc_name: str, target_dir: str) -> str:
        """Exporta los UDTs (User Data Types) del PLC a archivos Simatic Source Documents (.s7dcl) en target_dir.

        Fail-Fast: target_dir debe ser una ruta absoluta. No se almacena en caché.
        """
        if not Path(target_dir).is_absolute():
            raise ValueError(
                f"target_dir debe ser una ruta absoluta. Recibido: '{target_dir}'"
            )

        return await self._dispatch_worker(
            "export_udts_sd",
            {"plc_name": plc_name, "target_dir": target_dir},
        )

    async def export_plc_tags_xml(
        self,
        plc_name: str,
        target_dir: str,
        table_names: list[str] | None = None,
    ) -> str:
        """Exporta las tablas de variables (PLC tags) del PLC como XML SimaticML.

        Fail-Fast: target_dir debe ser una ruta absoluta. No se almacena en caché
        (acción mutable que vuelca archivos a disco).

        Args:
            plc_name: nombre del PLC destino.
            target_dir: ruta absoluta del directorio donde escribir los XML.
            table_names: si se pasa, SOLO se exportan las tablas cuyos
                nombres esten en esta lista. Si es ``None`` (default), se
                exportan TODAS las tablas del PLC (back-compat con el
                comportamiento previo).
        """
        if not Path(target_dir).is_absolute():
            raise ValueError(
                f"target_dir debe ser una ruta absoluta. Recibido: '{target_dir}'"
            )

        args: dict[str, Any] = {"plc_name": plc_name, "target_dir": target_dir}
        if table_names is not None:
            args["table_names"] = list(table_names)

        return await self._dispatch_worker("export_plc_tags_xml", args)

    async def attach_portal(self) -> bool:
        """Hot-attach a una instancia YA EJECUTÁNDOSE de TIA Portal.

        Escenario típico: el operario ya tiene TIA Portal abierto; el
        gateway se acopla a esa instancia vía ``ts.attach_portal()``
        (Manual V1.2.1 §2.4.2). No abre proyecto — solo establece la
        conexión COM.

        Returns:
            ``True`` si el acople fue exitoso.
        """
        return await self._dispatch_worker("attach_portal")

    async def open_new_portal(self, project_file_path: str) -> bool:
        """Cold start: lanza TIA Portal NUEVO y abre un proyecto.

        Sigue el Manual V1.2.1 §2.4.1:
          1. ``ts.open_portal()`` → instancia nueva del portal.
          2. ``portal.open_project(project_file_path)`` → abre proyecto.

        Args:
            project_file_path: Ruta absoluta al archivo ``.apxx``.

        Returns:
            ``True`` si la operación fue exitosa.
        """
        if not Path(project_file_path).is_absolute():
            raise ValueError(
                f"project_file_path debe ser absoluto. Recibido: '{project_file_path}'"
            )
        return await self._dispatch_worker(
            "open_new_portal",
            {"project_file_path": project_file_path},
        )

    async def open_project(self, project_file_path: str) -> None:
        """Abre un proyecto TIA Portal. Invalida caché del gateway (cambio de proyecto)."""
        if not Path(project_file_path).is_absolute():
            raise ValueError(
                f"project_file_path debe ser absoluto. Recibido: '{project_file_path}'"
            )
        await self._dispatch_worker(
            "open_project", {"project_file_path": project_file_path}
        )
        self.clear_cache()  # Cambio de proyecto invalida todo el estado IT cacheado.

    async def save_project(self) -> None:
        await self._dispatch_worker("save_project", {})

    async def close_project(self) -> None:
        await self._dispatch_worker("close_project", {})
        self.clear_cache()

    async def import_blocks_sd(
        self,
        plc_name: str,
        import_dir: str,
        target_folder: str | None = None,
    ) -> bool:
        """Importa bloques de programa en formato Simatic Source Documents (.s7dcl) desde el disco al PLC.

        Fail-Fast: import_dir debe ser una ruta absoluta. La validación
        final de existencia del directorio la hace el worker antes de
        invocar el método COM (TIA Portal lanza excepciones graves si el
        directorio no existe; ver manual §2.2.23).
        """
        if not Path(import_dir).is_absolute():
            raise ValueError(
                f"import_dir debe ser una ruta absoluta. Recibido: '{import_dir}'"
            )

        return await self._dispatch_worker(
            "import_blocks_sd",
            {
                "plc_name": plc_name,
                "import_dir": import_dir,
                "target_folder": target_folder,
            },
        )

    async def import_plc_tags_xml(
        self,
        plc_name: str,
        import_dir: str,
        target_folder: str | None = None,
    ) -> bool:
        """Importa tablas de variables (PLC tags) en formato XML al PLC.

        Fail-Fast: import_dir debe ser una ruta absoluta. La validación
        final de existencia del directorio la hace el worker antes de
        invocar el método COM (manual §2.2.24).
        """
        if not Path(import_dir).is_absolute():
            raise ValueError(
                f"import_dir debe ser una ruta absoluta. Recibido: '{import_dir}'"
            )

        return await self._dispatch_worker(
            "import_plc_tags_xml",
            {
                "plc_name": plc_name,
                "import_dir": import_dir,
                "target_folder": target_folder,
            },
        )

    async def export_block(
        self, plc_name: str, block_name: str, target_dir: str
    ) -> str:
        """Exporta un único bloque como .scl. No cachea (operación mutable)."""
        if not Path(target_dir).is_absolute():
            raise ValueError(
                f"target_dir debe ser absoluto. Recibido: '{target_dir}'"
            )
        return await self._dispatch_worker(
            "export_block",
            {"plc_name": plc_name, "block_name": block_name, "target_dir": target_dir},
        )

    async def import_block(
        self, plc_name: str, import_dir: str, target_folder: str | None = None
    ) -> bool:
        """Importa un único bloque (.scl) al PLC."""
        if not Path(import_dir).is_absolute():
            raise ValueError(
                f"import_dir debe ser absoluto. Recibido: '{import_dir}'"
            )
        return await self._dispatch_worker(
            "import_block",
            {
                "plc_name": plc_name,
                "import_dir": import_dir,
                "target_folder": target_folder,
            },
        )

    async def export_tag_table(
        self, plc_name: str, table_name: str, target_dir: str
    ) -> str:
        """Exporta una única PlcTagTable como XML. No cachea."""
        if not Path(target_dir).is_absolute():
            raise ValueError(
                f"target_dir debe ser absoluto. Recibido: '{target_dir}'"
            )
        return await self._dispatch_worker(
            "export_tag_table",
            {"plc_name": plc_name, "table_name": table_name, "target_dir": target_dir},
        )

    async def import_tag_table(
        self, plc_name: str, import_dir: str, target_folder: str | None = None
    ) -> bool:
        """Importa una única PlcTagTable (XML) al PLC."""
        if not Path(import_dir).is_absolute():
            raise ValueError(
                f"import_dir debe ser absoluto. Recibido: '{import_dir}'"
            )
        return await self._dispatch_worker(
            "import_tag_table",
            {
                "plc_name": plc_name,
                "import_dir": import_dir,
                "target_folder": target_folder,
            },
        )

    async def get_user_constants(
        self, plc_name: str, table_name: str
    ) -> dict[str, str]:
        """Inspecciona PlcUserConstant de una tabla. Devuelve {value: name}."""
        return await self._dispatch_worker(
            "get_user_constants",
            {"plc_name": plc_name, "table_name": table_name},
        )

    async def update_user_constant_value(
        self, plc_name: str, table_name: str, constant_name: str, new_value: int
    ) -> bool:
        """Actualiza el valor de una PlcUserConstant. Invalida caché de bloques."""
        result = await self._dispatch_worker(
            "update_user_constant_value",
            {
                "plc_name": plc_name,
                "table_name": table_name,
                "constant_name": constant_name,
                "new_value": new_value,
            },
        )
        self.clear_cache()  # Cambio de N_MAX puede afectar dimensiones de DBs.
        return result

    async def update_user_constant_name(
        self, plc_name: str, table_name: str, current_name: str, new_name: str
    ) -> bool:
        """Renombra una PlcUserConstant."""
        return await self._dispatch_worker(
            "update_user_constant_name",
            {
                "plc_name": plc_name,
                "table_name": table_name,
                "current_name": current_name,
                "new_name": new_name,
            },
        )

    async def delete_user_constant(
        self, plc_name: str, table_name: str, constant_name: str
    ) -> bool:
        """Borra una PlcUserConstant."""
        return await self._dispatch_worker(
            "delete_user_constant",
            {
                "plc_name": plc_name,
                "table_name": table_name,
                "constant_name": constant_name,
            },
        )

    async def execute_transactional_batch(
        self, operations: list[dict[str, Any]], undo_text: str = "Batch Operation"
    ) -> dict[str, Any]:
        """Ejecuta un lote de comandos en una transacción atómica del motor OT.

        Delega en el worker `_cmd_execute_transactional_batch`, que aísla
        toda la cadena bajo `project.start_transaction()` / `end_transaction`
        y aplica rollback automático si cualquier operación falla. Esto
        garantiza atomicidad en el historial de TIA Portal (Undo) y elimina
        estados intermedios inconsistentes.

        Args:
            operations: Lista de operaciones con la forma
                        [{"command": str, "args": dict}, ...]. El nombre
                        del comando omite el prefijo 'tia_' (uso interno).
            undo_text:  Etiqueta visible en el historial de Undo de TIA Portal.

        Returns:
            dict[str, Any] con {"success": True, "operations_executed": int}.

        Raises:
            RuntimeError: Si la lista está vacía, contiene un comando
                          desconocido o prohibido, o si cualquier operación
                          interna falla (incluye rollback automático).

        Timeout dinámico:
            El stage ``open_transaction`` del worker cubre la transacción
            COM completa. Con 50-100 ops en un PLC real puede tardar
            1-3 min; con 200+ ops, hasta 7-10 min. Aplicamos la fórmula
            ``max(default, num_ops × 5s)`` para cubrirnos las espaldas
            sin pasarnos: 5s por op es ~10× el tiempo medio observado
            en PLCs reales, así que tenemos margen sin pagar timeouts
            absurdos en operaciones pequeñas. El default
            (``DEFAULT_GATEWAY_TIMEOUT``) actúa como suelo: una sola op
            no baja del default.
        """
        per_op_seconds = 5.0
        n_ops = max(1, len(operations))
        dynamic_timeout = max(self._timeout, per_op_seconds * n_ops)
        return await self._dispatch_worker(
            "execute_transactional_batch",
            {"operations": operations, "undo_text": undo_text},
            timeout_override=dynamic_timeout,
        )

    async def commit_devices_sync(
        self,
        plc_name: str,
        nmax_ops: list[dict[str, Any]],
        rename_ops: list[dict[str, Any]],
        device_changes: list[dict[str, Any]],
        work_dir: str,
        undo_text: str = "Sync dispositivos (N_MAX + devices)",
    ) -> dict[str, Any]:
        """Commit atomico N_MAX + renames + devices en UNA sola transaccion TIA.

        Wrapper sobre ``execute_transactional_batch`` que emite UN SOLO op
        (``commit_devices_sync``) el cual, dentro del worker, abre una
        unica ``start_transaction`` y aplica:

          1. N_MAX online (``update_user_constant_value`` por cada uno).
          2. Renames online (``update_user_constant_name`` por cada uno).
          3. Devices: por cada tabla con adds o removes, export selectivo
             → edit XML offline (con ``TagTableModifier``) → import selectivo.

        Si CUALQUIER paso falla, el worker ejecuta
        ``end_transaction(rollback=True)`` y la excepcion se propaga al
        caller. El ``timeout_override`` se calcula como en
        ``execute_transactional_batch`` para cubrir el peor caso de
        N_MAX + renames + devices en un PLC grande.

        Args:
            plc_name: nombre del PLC destino en TIA.
            nmax_ops: lista de ``{table_name, constant_name, new_value}``
                (online).
            rename_ops: lista de ``{table_name, current_name, new_name}``
                (online).
            device_changes: lista de ``{table_name, tia_folder, adds,
                removes}`` (offline, solo tablas con adds o removes).
            work_dir: ruta absoluta del directorio donde el worker escribe
                los XML exportados/modificados.
            undo_text: texto del historial Undo de TIA.

        Returns:
            Dict con shape de ``execute_transactional_batch``:
            ``{"success": True, "operations_executed": int, "details": [...]}``.
        """
        if not Path(work_dir).is_absolute():
            raise ValueError(
                f"work_dir debe ser una ruta absoluta. Recibido: '{work_dir}'"
            )

        # Estimacion de ops para el timeout dinamico: N_MAX + renames +
        # 3 ops por cada device_change (export + edit + import).
        estimated_ops = 2  # start + end transaction
        estimated_ops += len(nmax_ops)
        estimated_ops += len(rename_ops)
        estimated_ops += 3 * len(device_changes)
        per_op_seconds = 5.0
        dynamic_timeout = max(self._timeout, per_op_seconds * estimated_ops)

        return await self._dispatch_worker(
            "execute_transactional_batch",
            {
                "operations": [{
                    "command": "commit_devices_sync",
                    "args": {
                        "plc_name": plc_name,
                        "undo_text": undo_text,
                        "work_dir": work_dir,
                        "nmax_ops": list(nmax_ops),
                        "rename_ops": list(rename_ops),
                        "device_changes": list(device_changes),
                    },
                }],
                "undo_text": undo_text,
            },
            timeout_override=dynamic_timeout,
        )

    async def update_disp_instance_comments_batch(
        self,
        plc_name: str,
        dispositivos_slot_maps: dict[str, dict[int, str]],
        target_folder: str,
        db_names: dict[str, str],
        db_array_names: dict[str, str],
        build_cache_dir: Path | None = None,
        undo_text: str = "Sync comentarios dispositivos",
    ) -> dict[str, Any]:
        """Aplica los comentarios por instancia a los 6 DBs de dispositivos
        en una sola transacción TIA con rollback atómico.

        Misma convención que ``SyncDispositivosInstancesUseCase``:
        el directorio de trabajo es ``<build_cache>/comments/`` (con
        ``build_cache = Path(os.getcwd()) / ".build_cache"`` por defecto).
        El directorio se conserva tras la operación (igual que ``base/tags/``
        y ``ready_to_import/tags/`` del sync de devices) para permitir
        inspección manual y diff con ``git diff``.

        Args:
            plc_name: nombre del PLC en TIA.
            dispositivos_slot_maps: ``{hw_type: {slot: texto}}`` con
                ``slot_map[0] == "NO USAR"`` siempre. Tipos activos:
                ``"ed", "ea", "sa", "v", "m", "m_vf"``.
            target_folder: carpeta destino del import dentro del proyecto
                TIA (resuelta por ``ConfigManager.get_tia_folder_dispositivos()``).
            db_names: ``{hw_type: db_name}`` ya resuelto por ConfigManager.
            db_array_names: ``{hw_type: db_array_name}`` ya resuelto por ConfigManager.
            build_cache_dir: ruta al directorio ``.build_cache``. Si es
                None, se usa ``Path(os.getcwd()) / ".build_cache"``.
            undo_text: etiqueta del historial Undo de TIA Portal.

        Returns:
            Dict con shape de ``execute_transactional_batch``:
            ``{"success": True, "operations_executed": int, "details": [...],
               "work_dir": str}``.

        Raises:
            ValueError: si algún ``slot_map[0] != "NO USAR"`` o si falta info.
        """
        if not dispositivos_slot_maps:
            raise ValueError("dispositivos_slot_maps está vacío.")

        import os

        if build_cache_dir is None:
            build_cache_dir = Path(os.getcwd()) / ".build_cache"
        work_dir = Path(build_cache_dir) / "comments"
        work_dir.mkdir(parents=True, exist_ok=True)

        operations: list[dict[str, Any]] = []
        for hw_type, slot_map in dispositivos_slot_maps.items():
            if 0 not in slot_map or slot_map[0] != "NO USAR":
                raise ValueError(
                    f"slot_map[{hw_type!r}][0] debe ser 'NO USAR' "
                    f"(got {slot_map.get(0)!r})."
                )
            operations.append({
                "command": f"update_disp_comments_db_{hw_type}",
                "args": {
                    "plc_name":      plc_name,
                    "db_name":       db_names.get(hw_type, ""),
                    "db_array_name": db_array_names.get(hw_type, ""),
                    "slot_map":      {str(k): v for k, v in slot_map.items()},
                    "work_dir":      str(work_dir),
                    "target_folder": target_folder,
                },
            })
        result = await self.execute_transactional_batch(
            operations, undo_text=undo_text
        )
        self.clear_cache()
        return result
