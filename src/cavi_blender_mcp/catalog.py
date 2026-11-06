"""Keep the discovery catalog compact without changing validation constraints."""

from cavi_mcp_core.server import Server


def omit_null_defaults(value):
    if isinstance(value, dict):
        return {key: omit_null_defaults(item) for key, item in value.items()
                if key != 'default' or item is not None}
    if isinstance(value, list):
        return [omit_null_defaults(item) for item in value]
    return value


class BlenderServer(Server):
    async def list_tools(self):
        tools = await super().list_tools()
        if not self.compact_schemas:
            return tools
        return [tool.model_copy(update={'input_schema': omit_null_defaults(tool.input_schema),
                                        'output_schema': omit_null_defaults(tool.output_schema)}) for tool in tools]
