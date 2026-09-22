import re
from pathlib import Path

# 1) Leer orquestador
orch_path = Path('areas/alimentacion/helpers/proc/proc_sincronizar.py')
orch_text = orch_path.read_text(encoding='utf-8')

# 2) Extraer ProcSyncContext
ctx_match = re.search(r'@dataclass\nclass ProcSyncContext:.*?(?=\n\ndef proc_)', orch_text, re.DOTALL)
if not ctx_match:
    raise SystemExit(1)
proc_sync_context = ctx_match.group(0)
print(f'ProcSyncContext: {len(proc_sync_context)} chars')

# 3) Extraer bloque de funciones publicas: desde proc_check_state_commit hasta antes de helpers privados (def _[a-z])
# Encontrar donde empiezan las helpers privadas
helpers_start_match = re.search(r'\n\n(def|async def) _[a-z_]+\(', orch_text)
if not helpers_start_match:
    raise SystemExit(1)
helpers_start_idx = helpers_start_match.start()

# Encontrar inicio de proc_check_state_commit
funcs_start_match = re.search(r'\n\ndef proc_check_state_commit\(', orch_text)
if not funcs_start_match:
    raise SystemExit(1)
funcs_start_idx = funcs_start_match.start() + 2  # saltar el "\n\n" inicial

public_funcs = orch_text[funcs_start_idx:helpers_start_idx]
print(f'Public functions: {len(public_funcs)} chars')

# 4) Extraer helpers privados: desde helpers_start_idx hasta el final
private_helpers = orch_text[helpers_start_idx+2:]  # saltar "\n\n"
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
fb_text_new = fb_text_new.replace('nombre: str = "proc_sincronizar"', 'nombre: str = "proc_db_sincronizar"')

# Eliminar import lazy y creacion de ProcSyncContext
fb_text_new = re.sub(
    r'        # Lazy import para evitar ciclo con helpers/proc/\.\n        from areas\.alimentacion\.helpers\.proc import proc_sincronizar\n\n',
    '',
    fb_text_new
)
fb_text_new = re.sub(
    r'        # Crear el ProcSyncContext que las N funciones iran mutando\.\n        # Lazy import para evitar ciclo con helpers/proc/\.\n        from areas\.alimentacion\.helpers\.proc\.proc_sincronizar import \(\n            ProcSyncContext,\n        \)\n        self\._ctx = ProcSyncContext\(\n[^)]*\n        \)\n',
    '',
    fb_text_new
)

# Insertar antes de "def _step_summary"
insert_marker = 'def _step_summary('
idx = fb_text_new.find(insert_marker)
if idx < 0:
    raise SystemExit(1)
fb_text_new = fb_text_new[:idx] + new_section + '\n\n\n' + fb_text_new[idx:]

fb_path.write_text(fb_text_new, encoding='utf-8')
print(f'Saved {fb_path}, total: {len(fb_text_new)} chars')