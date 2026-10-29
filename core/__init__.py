"""Nucleo transversal de la app (OB1 + DDD-like layout).

Subpaquetes:
  data/           Value Objects y DTOs.
  composition/    Wiring (engine, FBs, area registry).
  helpers/        Logica pura transversal (TIA, bloques, Simatic SD).
  infrastructure/ Adaptadores externos (TIA Portal, config, logs).
  launcher/       Bandeja, supervisor y arranque de la app.
  runtime/        Estado global + buffers + SSE.
  web_server/     Shell Flask + SPA.
"""
