"""Shared OAuth 2.0 auth for ForgeLab (REST API + future MCP server).

Domain-agnostic: imports nothing from forgelab.{core,spec,formats,importers,
exporters,sdk}. Only ``forgelab.auth.fastapi`` imports FastAPI.
"""
