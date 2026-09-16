"""Modificadores SimaticSD (.s7dcl) del subdominio alimentación.

Submódulos:
  - ``simatic_sd_disp_comment_updater``: actualiza comentarios de los 6 DBs de dispositivos.
  - ``simatic_sd_proc_comment_updater``: actualiza comentarios de los 3 arrays de procesos.
  - ``simatic_sd_mlc_registry``: registro de IDs MLC únicos.

Restricción arquitectónica: este paquete NO importa ``siemens_tia_scripting``.

Nota: los submódulos NO se re-exportan aquí para evitar circular imports.
Los consumers hacen ``from areas.alimentacion.helpers.simatic_sd.simatic_sd_X import Y`` directamente.
"""
