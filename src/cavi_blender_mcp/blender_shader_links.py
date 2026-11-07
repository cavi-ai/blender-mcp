"""Atomic rewiring of existing shader sockets in one inspected node tree."""

from .blender_errors import preflight
from .blender_shader_inputs import editable_node, finish_edit, update
from .shader_links import bindings, compatible


def socket(node,side,identifier):
    value=next((s for s in getattr(node,side) if s.identifier==identifier),None)
    if value is None or value.bl_idname=='NodeSocketVirtual':
        raise ValueError('Exact shader socket does not exist: '+identifier)
    return value


def endpoints(link):
    return link.from_socket,link.to_socket


def describe(pair):
    source,target=pair
    return {'from_node':source.node.name,'from_socket':source.identifier,
            'to_node':target.node.name,'to_socket':target.identifier}


def apply(tree,changes,connect):
    for source,target,_old in changes:
        for link in list(target.links):
            tree.links.remove(link)
        if connect:
            tree.links.new(source,target,verify_limits=False,handle_dynamic_sockets=False)
    update(tree)


def validate_graph(tree,changes):
    targets={target for _source,target,_old in changes}
    edges={n:set() for n in tree.nodes}
    for link in tree.links:
        if link.to_socket not in targets:
            edges[link.from_node].add(link.to_node)
    for source,target,_old in changes:
        edges[source.node].add(target.node)
    for source,target,_old in changes:
        pending,seen=[target.node],set()
        while pending:
            node=pending.pop()
            if node==source.node:
                raise ValueError('Shader connection would create a cycle')
            if node not in seen:
                seen.add(node)
                pending.extend(edges[node])
    for source,target,_old in changes:
        if not compatible(source.type,target.type):
            raise ValueError('Native shader sockets cannot be connected')
        projected=sum(l.to_socket not in targets for l in source.links)+sum(s==source for s,_t,_o in changes)
        if source.link_limit and projected>source.link_limit:
            raise ValueError('Shader output connection limit would be exceeded')


def edit_links(params):
    with preflight():
        action=params.get('action')
        replace=params.get('update_existing',False)
        if action not in {'connect','disconnect'} or type(replace) is not bool or (action=='disconnect' and replace):
            raise ValueError('Invalid shader link action or replacement flag')
        tree,node=editable_node(params)
        changes=[]
        flags={}
        for identifier,binding in bindings(params.get('inputs')).items():
            target=socket(node,'inputs',identifier)
            source_node=tree.nodes.get(binding['node'])
            if source_node is None:
                raise ValueError('Shader source node does not exist: '+binding['node'])
            source=socket(source_node,'outputs',binding['socket'])
            links=list(target.links)
            if target.is_multi_input or len(links)>1:
                raise ValueError('Shader link edits require single-input sockets')
            old=endpoints(links[0]) if links else None
            if links:
                flags[target]=(links[0].is_muted,links[0].is_valid)
            if action=='connect':
                if any(not s.enabled or s.is_unavailable for s in (source,target)):
                    raise ValueError('Shader sockets must be enabled and available')
                if old==(source,target):
                    continue
                if old and not replace:
                    raise ValueError('Occupied shader input requires update_existing=true')
            elif old!=(source,target):
                raise ValueError('Disconnect binding differs from the current shader link')
            changes.append((source,target,old))
        if action=='connect' and changes:
            validate_graph(tree,changes)
        invalid_before={endpoints(link) for link in tree.links if not link.is_valid}
    try:
        if changes:
            apply(tree,changes,action=='connect')
            for source,target,_old in changes:
                links=list(target.links)
                if ((action=='disconnect' and links) or (action=='connect' and
                        (len(links)!=1 or links[0].from_socket!=source or not links[0].is_valid))):
                    raise RuntimeError('Native shader link readback differs from the requested edit')
            if any(not link.is_valid and endpoints(link) not in invalid_before for link in tree.links):
                raise RuntimeError('Shader edit invalidated another connection')
        return finish_edit(params,tree,bool(changes),changed_links=[{
            'before':describe(old) if old else None,
            'after':describe((source,target)) if action=='connect' else None}
            for source,target,old in changes])
    except Exception:
        for _source,target,old in changes:
            for link in list(target.links):
                tree.links.remove(link)
            if old:
                restored=tree.links.new(*old,verify_limits=False,handle_dynamic_sockets=False)
                restored.is_muted,restored.is_valid=flags[target]
        update(tree)
        raise
