"""Copy authored shader controls while retaining external resource references."""
import bpy

from .blender_errors import preflight
from .blender_material_bindings import bind, capture, restore
from .blender_shader_inputs import inspect


def dispose_graph(material, groups):
    if material is not None:
        bpy.data.materials.remove(material)
    if groups:
        bpy.data.batch_remove(ids=tuple(groups))


def clone_graph(source, name=None):
    material=None
    groups=[]
    try:
        material=source.copy()
        material.use_fake_user=False
        mappings={source.node_tree:material.node_tree} if source.node_tree else {}
        pending=[material.node_tree] if material.node_tree else []
        while pending:
            tree=pending.pop()
            for node in tree.nodes:
                if node.type!='GROUP' or node.node_tree is None:
                    continue
                original=node.node_tree
                if original not in mappings:
                    clone=original.copy()
                    groups.append(clone)
                    clone.use_fake_user=False
                    mappings[original]=clone
                    pending.append(clone)
                node.node_tree=mappings[original]
        if name is not None:
            material.name=name
            if material.name!=name or material.library is not None:
                raise RuntimeError('Native copy did not produce the requested local material')
        return material,groups,mappings
    except Exception:
        dispose_graph(material,groups)
        raise


def make_unique(params, find_object):
    with preflight():
        names=params.get('names')
        name=params.get('material_name')
        slot,mode=params.get('slot',0),params.get('link_mode','OBJECT')
        if (not isinstance(names,list) or not 1<=len(names)<=32
                or any(not isinstance(n,str) or not n for n in names) or len(set(names))!=len(names)):
            raise ValueError('Choose 1..32 unique mesh names')
        if not isinstance(name,str) or not name.strip() or not 1<=len(name.encode())<=63:
            raise ValueError('Material name must contain 1..63 UTF-8 bytes')
        if bpy.data.materials.get(name) is not None:
            raise ValueError('New material name already exists')
        if type(slot) is not int or not 0<=slot<=31 or mode not in {'OBJECT','DATA'}:
            raise ValueError('Use slot 0..31 and OBJECT or DATA link mode')
        values=[find_object(n,mesh=True) for n in names]
        sources=[]
        for value in values:
            if not value.is_editable:
                raise ValueError('Target requires an editable scene object')
            if slot>=len(value.material_slots) or value.material_slots[slot].material is None:
                raise ValueError('Requested slot must have a source material')
            if mode=='DATA' and (value.data.users!=1 or not value.data.is_editable):
                raise ValueError('DATA bindings require single-user editable mesh data')
            sources.append(value.material_slots[slot].material)
        source=sources[0]
        if any(s!=source for s in sources):
            raise ValueError('Selected slots must use the same source material')
        saved=capture(values)
    material=None
    groups=[]
    try:
        material,groups,mappings=clone_graph(source,name)
        bind(values,material,slot,{v:mode for v in values})
        rows=[{'source':old.name,'name':new.name} for old,new in mappings.items()
              if old!=source.node_tree]
        return {**inspect({'material_name':material.name}), 'objects':names, 'slot':slot,
            'bindings':[{'object':v.name,'link_mode':mode,'mesh':v.data.name,'mesh_users':v.data.users}
                        for v in values],
            'material_copy':{'source':source.name,'node_group_count':len(groups),
                'node_groups':rows[:1000],'groups_truncated':len(rows)>1000,
                'images_shared':True,'actions_shared':True}}
    except Exception:
        restore(saved)
        dispose_graph(material,groups)
        raise
