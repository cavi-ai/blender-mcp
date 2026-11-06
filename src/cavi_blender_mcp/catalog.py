"""Keep the discovery catalog compact without changing validation constraints."""

from cavi_mcp_core.schema import compact_schema
from cavi_mcp_core.server import Server as BlenderServer

__all__ = ['BlenderServer', 'omit_null_defaults']


def omit_null_defaults(value):
    """Use the shared schema walker, preserving literal dictionaries and constraints."""
    return compact_schema(value)
