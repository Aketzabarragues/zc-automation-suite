"""Adaptadores externos del nucleo.

Capa transversal que conecta el core con el mundo exterior: TIA Portal
(via tia/), config del proyecto (via config/), el bridge de logs a la
SPA (via log/) y persistencia local. NO sabe de areas concretas:
expone interfaces comunes que las areas extienden via
AreaSpec.contributes_*.

_pendiente/ contiene legacy que se ira migrando a medida que las areas
se adapten al modelo OB1.
"""
