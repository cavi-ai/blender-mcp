"""Locate and expose a numeric shader socket without rebuilding its input context."""


def locate(material, spec):
    tree=material.node_tree
    parents=[]
    if tree is None:
        raise ValueError('Source material needs shader nodes')
    for name in spec.get('group_path',[]):
        node=tree.nodes.get(name)
        if node is None or node.type!='GROUP' or node.node_tree is None:
            raise ValueError(f'No shader group: {name}')
        parents.append((tree,node))
        tree=node.node_tree
    node=tree.nodes.get(spec['node'])
    if node is None:
        raise ValueError('Source shader node does not exist')
    sockets=node.inputs if spec.get('direction','OUTPUT')=='INPUT' else node.outputs
    socket=next((s for s in sockets if s.identifier==spec['socket']),None)
    if socket is None or socket.type not in {'VALUE','INT','BOOLEAN','RGBA','VECTOR'}:
        raise ValueError('Choose an existing numeric, color or vector socket identifier')
    if not socket.enabled or socket.is_unavailable:
        raise ValueError('Source socket is unavailable for this node configuration')
    if not socket.is_output and len(socket.links)>1:
        raise ValueError('Source input must have at most one link')
    return tree,socket,parents


def expose(material, spec):
    """Called only on private graph copies; group instances keep their actual inputs."""
    tree,socket,parents=locate(material,spec)
    if not socket.is_output:
        if socket.is_linked:
            socket=socket.links[0].from_socket
        elif socket.type in {'VALUE','INT','BOOLEAN'}:
            node=tree.nodes.new('ShaderNodeValue')
            node.outputs[0].default_value=float(socket.default_value)
            socket=node.outputs[0]
        else:
            node=tree.nodes.new('ShaderNodeCombineXYZ')
            for target,value in zip(node.inputs,socket.default_value[:3],strict=True):
                target.default_value=value
            socket=node.outputs[0]
    for parent,instance in reversed(parents):
        interface=tree.interface.new_socket(name='CAVI Bake Channel',in_out='OUTPUT',
                                            socket_type='NodeSocketColor')
        output=next((n for n in tree.nodes if n.type=='GROUP_OUTPUT' and n.is_active_output),None)
        if output is None:
            output=tree.nodes.new('NodeGroupOutput')
            output.is_active_output=True
        tree.links.new(socket,output.inputs[interface.identifier])
        socket=instance.outputs[interface.identifier]
        tree=parent
    return socket


def route(material, spec, image):
    socket=expose(material,spec)
    tree=material.node_tree
    outputs=[n for n in tree.nodes if n.type=='OUTPUT_MATERIAL' and n.is_active_output
             and n.target in {'ALL','CYCLES'}]
    output=next((n for n in outputs if n.target=='CYCLES'),None)
    output=output or next(iter(outputs),None) or tree.nodes.new('ShaderNodeOutputMaterial')
    output.is_active_output=True
    # Two nonnegative passes retain signed channels despite emission's negative clamp.
    scale=tree.nodes.new('ShaderNodeVectorMath')
    scale.operation='SCALE'
    scale.inputs['Scale'].default_value=1
    tree.links.new(socket,scale.inputs[0])
    positive=tree.nodes.new('ShaderNodeVectorMath')
    positive.operation='MAXIMUM'
    positive.inputs[1].default_value=(0,0,0)
    tree.links.new(scale.outputs['Vector'],positive.inputs[0])
    emission=tree.nodes.new('ShaderNodeEmission')
    tree.links.new(positive.outputs['Vector'],emission.inputs['Color'])
    tree.links.new(emission.outputs[0],output.inputs['Surface'])
    target=tree.nodes.new('ShaderNodeTexImage')
    target.image=image
    tree.nodes.active=target
    return scale.inputs['Scale']
