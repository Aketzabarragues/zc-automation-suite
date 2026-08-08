"""Parsers de formatos externos (Excel, XML SimaticML).

Capa de infraestructura offline. Restricción arquitectónica:
**prohibido** importar ``siemens_tia_scripting`` aquí; los parsers
operan sobre archivos ya exportados, no invocan la API de TIA Portal.
"""
