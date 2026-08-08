"""Modificadores de Simatic Source Documents (.s7dcl) para bloques.

Clase responsable de inyectar llamadas de instancia entre marcadores
de un archivo .s7dcl exportado por ``TIAProcessGateway.export_blocks_sd``.

Restricción arquitectónica: este módulo es OFFLINE; no importa
``siemens_tia_scripting``.
"""
