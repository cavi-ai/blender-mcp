"""Transactional edits to existing native shader-node controls."""
from .blender_animation_refs import require_static
from .blender_errors import preflight
from .blender_node_inputs import encode
from .blender_shader_inputs import editable, editable_node, finish_edit, update
from .blender_shader_links import socket
from .blender_shader_nodes import active_outputs, control_schema, restore_outputs
from .native_controls import controls, equivalent


def link_key(link):
    return (link.from_node.name,link.from_socket.identifier,link.to_node.name,link.to_socket.identifier)


def references(owner,path,node,keys):
    prefix,separator,key=path.rpartition('.')
    if not separator or key not in keys or owner is None:return False
    try:return owner.path_resolve(prefix,False)==node
    except (ValueError,KeyError,TypeError):return False


def defaults(node):
    return [(side,s.identifier,s.bl_idname,encode(s.default_value))
        for side in ('inputs','outputs') for s in getattr(node,side) if editable(s)]


def restore_defaults(node,values):
    for side,identifier,kind,value in values:
        target=socket(node,side,identifier)
        if target.bl_idname!=kind:raise RuntimeError('Rollback could not restore the original shader socket type')
        if not equivalent(encode(target.default_value),value):target.default_value=value


def restore_links(tree,links):
    expected={row[0] for row in links}
    for link in list(tree.links):
        if link_key(link) not in expected:tree.links.remove(link)
    current={link_key(link):link for link in tree.links}
    for key,muted,valid in links:
        link=current.get(key)
        if link is None:
            source,source_id,target,target_id=key
            link=tree.links.new(socket(tree.nodes[source],'outputs',source_id),
                socket(tree.nodes[target],'inputs',target_id),verify_limits=False,handle_dynamic_sockets=False)
        link.is_muted,link.is_valid=muted,valid


def set_controls(params):
    with preflight():
        tree,node=editable_node(params)
        values=controls(params.get('node_settings'),control_schema(type(node),node),
            subject='shader node',parameter='node_settings')
        changed={key:value for key,value in values.items() if not equivalent(getattr(node,key),value)}
        if changed:require_static(lambda owner,path:references(owner,path,node,changed),'Shader node control',root=node.id_data)
        before={key:getattr(node,key) for key in changed}
        prior_defaults=defaults(node)
        prior_links=[(link_key(link),link.is_muted,link.is_valid) for link in tree.links]
        prior_outputs=active_outputs(tree)
    try:
        if changed:
            for key,value in changed.items():setattr(node,key,value)
            update(tree)
            if any(not equivalent(getattr(node,key),value) for key,value in values.items()):
                raise RuntimeError('Native node settings differ from the requested edit')
            if {key for key,_muted,_valid in prior_links}!={link_key(link) for link in tree.links}:
                raise RuntimeError('Native settings changed shader connections; disconnect them explicitly before editing this mode')
        return finish_edit(params,tree,bool(changed),changed_settings={
            key:{'before':before[key],'after':getattr(node,key)} for key in changed},
            changed_active_outputs=[{'node':item.name,'before':active,'after':item.is_active_output}
                for item,active in prior_outputs if item.is_active_output!=active])
    except Exception:
        if changed:
            for key,value in reversed(list(before.items())):setattr(node,key,value)
            restore_outputs(prior_outputs)
            update(tree)
            restore_defaults(node,prior_defaults)
            restore_links(tree,prior_links)
            update(tree)
        raise
