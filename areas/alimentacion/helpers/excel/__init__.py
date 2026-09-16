"""Excel: paquete del subdominio alimentación para todo lo relacionado con el Excel corporativo.

Submódulos:
  - ``excel_loader``: abre el workbook y construye el ``DataExcelCache``.
  - ``excel_cache_manager``: Singleton por proceso del caché.
  - ``_excel_helpers``: utilidades compartidas (``_safe_int``, ``extract_list_object_rows``).
  - ``excel_parser_*``: parsers de las 11 tablas del Excel corporativo.

Restricción arquitectónica: este paquete NO importa ``siemens_tia_scripting``.

Nota: los submódulos NO se re-exportan aquí para evitar circular imports
(excel_loader importa los parsers, los parsers importan _excel_helpers).
Los consumers hacen ``from areas.alimentacion.helpers.excel.excel_loader import ExcelLoader`` directamente.
"""
