"""Keep the discovery catalog compact without changing validation constraints."""
import json
import string
from collections import Counter

from cavi_mcp_core.contracts import failure
from cavi_mcp_core.schema import compact_schema
from cavi_mcp_core.schema_refs import map_schema, preserve_structure
from cavi_mcp_core.server import Server as CoreServer

__all__ = ['BlenderServer', 'omit_null_defaults']


def shared_constraints(schema):
    """Share repeated value constraints while retaining field annotations."""
    if not isinstance(schema,dict) or preserve_structure(schema):
        return schema
    constraints={'type','items','prefixItems','minItems','maxItems','minimum','maximum',
                 'exclusiveMinimum','exclusiveMaximum','multipleOf','minLength','maxLength','pattern'}
    annotations={'description','default','title','examples'}
    counts,values=Counter(),{}
    known={'#/$defs/'+k.replace('~','~0').replace('/','~1') for k in schema.get('$defs',{})}
    unknown=[]

    def signature(node):
        types=node.get('type')
        if (not isinstance(types,(str,list)) or (isinstance(types,list) and any(not isinstance(t,str) for t in types))
                or not set([types] if isinstance(types,str) else types)<={
                'array','boolean','integer','number','object','string','null'}):
            return None
        if set(node)-constraints-annotations:
            return None
        body={k:v for k,v in node.items() if k in constraints}
        return json.dumps(body,sort_keys=True,separators=(',',':'))

    def count(node):
        if '$ref' in node and node['$ref'] not in known:
            unknown.append(node['$ref'])
        key=signature(node)
        if key is not None:
            counts[key]+=1
            values[key]={k:v for k,v in node.items() if k in constraints}
        return node

    map_schema(schema,count)
    if unknown:return schema
    selected={key for key,n in counts.items() if (len(key)-20)*n>len(key)+5+(0 if known else 10)}
    if not selected:return schema
    definitions=dict(schema.get('$defs',{}))
    names={}
    for key in sorted(selected):
        name='shared'+str(len(definitions))
        while name in definitions:name+='a'
        definitions[name]=values[key]
        names[key]='#/$defs/'+name

    def replace(node):
        key=signature(node)
        if key in names:
            return {'$ref':names[key],**{k:v for k,v in node.items() if k not in constraints}}
        return node

    result=map_schema(schema,replace)
    # New definitions retain their bodies; only occurrences in the original schema move.
    result['$defs']={**result.get('$defs',{}),**{ref.split('/')[-1]:values[key] for key,ref in names.items()}}
    def size(value):
        return len(json.dumps(short_references(value),separators=(',',':'),ensure_ascii=False).encode())
    return result if size(result)<size(schema) else schema


def short_references(schema):
    """Rename only unscoped local definitions; literal JSON data stays untouched.

    Definitions that only point to another definition are bypassed.
    """
    if not isinstance(schema, dict) or not schema.get('$defs') or preserve_structure(schema):
        return schema

    def pointer(name):
        return '#/$defs/'+name.replace('~', '~0').replace('/', '~1')
    defined = {pointer(name) for name in schema['$defs']}
    links = {pointer(name): value['$ref'] for name, value in schema['$defs'].items()
             if isinstance(value, dict) and value.keys() == {'$ref'} and value['$ref'] in defined}

    def target(reference):
        seen = []
        while reference in links and reference not in seen:
            seen.append(reference)
            reference = links[reference]
        return None if reference in seen else reference
    aliases = {reference: end for reference in links if (end := target(reference)) is not None}
    empty = {pointer(name) for name, value in schema['$defs'].items() if value == {}}
    kept = [name for name in schema['$defs'] if pointer(name) not in aliases.keys() | empty]
    alphabet = string.ascii_letters + string.digits
    names = {name: alphabet[index] if index < len(alphabet) else f'd{index}'
             for index, name in enumerate(kept)}
    references = {pointer(name): '#/$defs/'+short for name, short in names.items()}
    unknown = []

    def check(node):
        reference = node.get('$ref', '')
        if isinstance(reference, str) and reference.startswith('#/$defs/') and reference not in defined:
            unknown.append(reference)
        return node

    map_schema(schema, check)
    if unknown:
        return schema

    def rewrite(node):
        reference = aliases.get(node.get('$ref'), node.get('$ref'))
        if reference in empty:
            return {key:value for key,value in node.items() if key!='$ref'}
        if reference in references:
            node['$ref'] = references[reference]
        return node

    result = map_schema(schema, rewrite)
    result['$defs'] = {names[name]: value for name, value in result['$defs'].items() if name in names}
    if not result['$defs']:
        result.pop('$defs')
    return map_schema(result,lambda node:{key:value for key,value in node.items()
                                          if key!='additionalProperties' or value!={}})


class BlenderServer(CoreServer):
    def failure(self, name, error):
        # Ownership state is read through session_control; everything else through scene_info.
        action = 'session_control' if name == 'session_control' else 'scene_info'
        return failure(name, error, unknown_next_action=action)

    async def list_tools(self):
        tools = await super().list_tools()
        if not self.compact_schemas:
            return tools
        result = []
        # Keep readOnlyHint explicit for clients that classify callable safety.
        defaults = {'idempotent_hint': False, 'open_world_hint': True}
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
                'input_schema': short_references(shared_constraints(tool.input_schema)),
                'output_schema': short_references(shared_constraints(tool.output_schema))}))
        return result


def omit_null_defaults(value):
    """Use the shared schema walker, preserving literal dictionaries and constraints."""
    return compact_schema(value)
