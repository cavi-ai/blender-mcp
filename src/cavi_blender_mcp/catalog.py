"""Keep the discovery catalog compact without changing validation constraints."""
import string

from cavi_mcp_core.schema import compact_schema
from cavi_mcp_core.schema_refs import map_schema, preserve_structure
from cavi_mcp_core.server import Server as CoreServer

__all__ = ['BlenderServer', 'omit_null_defaults']


def short_references(schema):
    """Rename only unscoped local definitions; literal JSON data stays untouched."""
    if not isinstance(schema, dict) or not schema.get('$defs') or preserve_structure(schema):
        return schema
    alphabet = string.ascii_letters + string.digits
    names = {name: alphabet[index] if index < len(alphabet) else f'd{index}'
             for index, name in enumerate(schema['$defs'])}
    references = {'#/$defs/'+name.replace('~', '~0').replace('/', '~1'): '#/$defs/'+short
                  for name, short in names.items()}
    unknown = []

    def check(node):
        reference = node.get('$ref', '')
        if isinstance(reference, str) and reference.startswith('#/$defs/') and reference not in references:
            unknown.append(reference)
        return node

    map_schema(schema, check)
    if unknown:
        return schema

    def rewrite(node):
        if node.get('$ref') in references:
            node['$ref'] = references[node['$ref']]
        return node

    result = map_schema(schema, rewrite)
    result['$defs'] = {names[name]: value for name, value in result['$defs'].items()}
    return result


class BlenderServer(CoreServer):
    async def list_tools(self):
        tools = await super().list_tools()
        if not self.compact_schemas:
            return tools
        result = []
        defaults = {'read_only_hint': False, 'destructive_hint': True,
                    'idempotent_hint': False, 'open_world_hint': True}
        for tool in tools:
            annotations = tool.annotations
            if annotations is not None:
                omitted = {key: None for key, value in defaults.items()
                           if getattr(annotations, key) is value}
                if annotations.read_only_hint is True:
                    # MCP defines these hints only for mutating tools.
                    omitted.update(destructive_hint=None, idempotent_hint=None)
                annotations = annotations.model_copy(update=omitted)
            result.append(tool.model_copy(update={'annotations': annotations,
                'input_schema': short_references(tool.input_schema),
                'output_schema': short_references(tool.output_schema)}))
        return result


def omit_null_defaults(value):
    """Use the shared schema walker, preserving literal dictionaries and constraints."""
    return compact_schema(value)
