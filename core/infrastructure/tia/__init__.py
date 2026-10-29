"""Subsistema TIA: el worker OT.

Aloja el hilo dedicado y su cola (tia_loop.py), los 27 comandos genericos
(los modulos tia_cmd_*.py y su catalogo central), las utilidades
defensivas (tia_helpers.py) y la carga del wrapper .NET (tia_loader.py).
Las areas extienden el registro de comandos via
AreaSpec.contributes_tia_commands.
"""
