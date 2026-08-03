"""Generic versioned template package tooling."""

from .models import TOOL_VERSION, METADATA_SCHEMA_VERSION, TemplateToolError

__all__ = ["METADATA_SCHEMA_VERSION", "TOOL_VERSION", "TemplateToolError"]
