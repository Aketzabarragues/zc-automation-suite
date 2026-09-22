import re
from pathlib import Path

# 1) Leer orquestador
orch_path = Path('areas/alimentacion/helpers/proc/proc_sincronizar.py')
orch_text = orch_path.read_text(encoding='utf-8')

# 2) Extraer ProcSyncContext
ctx_match = re.search(r'@dataclass\nclass ProcSyncContext:.*?(?=\n\ndef proc_)', orch_text, re.DOTALL)
if not ctx_match:
    print('FAIL: ProcSyncContext not found')
    raise SystemExit(1)
proc_sync_context = ctx_match.group(0)
print(f'ProcSyncContext: {len(proc_sync_context)} chars')

# 3) Extraer bloque de funciones publicas
funcs_match = re.search(r'\n\n(def proc_[a-z_]+.*?)(?=\n\ndef _[a-z])', orch_text, re.DOTALL)
if not funcs_match:
    print('FAIL: public functions not found')
    raise SystemExit(1)
public_funcs = funcs_match.group(1)
print(f'Public functions: {len(public_funcs)} chars')

# 4) Extraer helpers privados
helpers_match = re.search(r'\n\n(def _[a-z_]+.*?)$', orch_text, re.DOTALL)
if not helpers_match:
    print('FAIL: helpers not found')
    raise SystemExit(1)
private_helpers = helpers_match.group(1)
print(f'Private helpers: {len(private_helpers)} chars')

# 5) Transformar
def transform(text):
    out = text
    out = re.sub(r'\bctx\.', 'self._ctx.', out)
    out = re.sub(r'def (proc_[a-z_]+)\(ctx: ProcSyncContext\)', r'def \1(self)', out)
    out = re.sub(r'async def (proc_[a-z_]+)\(ctx: ProcSyncContext\)', r'async def \1(self)', out)
    return out

ctx_t = transform(proc_sync_context)
funcs_t = transform(public_funcs)
helpers_t = transform(private_helpers)

# 6) Construir bloque
new_section = '''
# ============================================================================
# Codigo absorbido de helpers/proc/proc_sincronizar.py (commit 22, sept-2026).
# Antes era un orquestador separado que el FB llamaba via ``match step_nombre``.
# Ahora vive como metodos del FB (mutando ``self._ctx``).
# ============================================================================

'''
new_section += ctx_t + '\n\n'
new_section += funcs_t + '\n\n'
new_section += helpers_t

# 7) Leer FB
fb_path = Path('areas/alimentacion/functions/function_proc_db_sincronizar.py')
fb_text = fb_path.read_text(encoding='utf-8')

# Renombrar clase
fb_text_new = fb_text.replace('class FunctionProcSincronizar', 'class FunctionProcDBSincronizar')

# Renombrar nombre canonico
fb_text_new = fb_text_new.replace('nombre: str = "proc_sincronizar"',
                                  'nombre: str = "proc_db_sincronizar"')

# Eliminar import lazy de proc_sincronizar
fb_text_new = re.sub(
    r'        # Lazy import para evitar ciclo con helpers/proc/\.\n        from areas\.alimentacion\.helpers\.proc import proc_sincronizar\n\n',
    '',
    fb_text_new
)

# Eliminar bloque de creacion del ProcSyncContext (reemplazado por creacion inline)
fb_text_new = re.sub(
    r'        # Crear el ProcSyncContext que las 11 funciones iran mutando\.\n        # Lazy import para evitar ciclo con helpers/proc/\.\n        from areas\.alimentacion\.helpers\.proc\.proc_sincronizar import \(\n            ProcSyncContext,\n        \)\n        self\._ctx = ProcSyncContext\(\n            plc_name=self\._plc_name,\n            proc_uid=self\._proc_uid,\n            tia_client=self\._tia_client,\n            config_manager=self\._config,\n            app_state=self\._state,\n            build_cache_root=self\._build_cache_root,\n            bloques_cache=self\._bloques_cache,\n            result=None,\n        \)\n',
    '',
    fb_text_new
)

# Reemplazar el bloque match del run_step
# Esto requiere regex mas cuidadosa. Vamos a leer primero el archivo.
# Lo dejo para el final: insertar codigo absorbido y luego ajustar match manualmente.

# Insertar antes de "def _step_summary"
insert_marker = 'def _step_summary('
idx = fb_text_new.find(insert_marker)
if idx < 0:
    print('FAIL: _step_summary not found')
    raise SystemExit(1)
fb_text_new = fb_text_new[:idx] + new_section + '\n\n\n' + fb_text_new[idx:]

fb_path.write_text(fb_text_new, encoding='utf-8')
print(f'Saved {fb_path}, total: {len(fb_text_new)} chars')