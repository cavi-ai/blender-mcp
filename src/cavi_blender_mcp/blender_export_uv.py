"""Promote a named UV atlas on temporary mesh data, retaining source actors."""
from contextlib import contextmanager

import bpy
import numpy as np

from .blender_errors import preflight
from .blender_material_bindings import capture, restore


def labels(names,name,primary):
    ordered=[name,*[label for label in names if label!=name]]
    return [primary if label==name else name if label==primary else label for label in ordered] if primary else ordered


def reorder(mesh,name,primary):
    layers=mesh.uv_layers
    rows=[]
    for layer in layers:
        values=np.empty(len(mesh.loops)*2,dtype=np.float32)
        layer.uv.foreach_get('vector',values)
        if not np.isfinite(values).all():
            raise ValueError('Export UVs must be finite')
        rows.append((layer.name,values))
    rows.sort(key=lambda row:row[0]!=name)
    exported=labels([row[0] for row in rows],name,primary)
    for layer in list(layers):layers.remove(layer)
    for label,(_,values) in zip(exported,rows,strict=True):
        layer=layers.new(name=label,do_init=False)
        if layer.name!=label:raise RuntimeError('Could not retain an exported UV layer name')
        layer.uv.foreach_set('vector',values)
    layers.active_index=0
    layers[0].active_render=True
    mesh.update()


@contextmanager
def promote(objects,name,primary=None):
    if name is None:
        yield None
        return
    with preflight():
        if not isinstance(name,str) or not 1<=len(name)<=63:
            raise ValueError('uv_layer must name an existing 1..63 character UV map')
        values=list(dict.fromkeys(value for value in objects if value.type=='MESH'))
        for value in values:
            if not value.is_editable or value.mode!='OBJECT':
                raise ValueError('UV export needs editable Object Mode actors')
            if value.data.uv_layers.get(name) is None:
                raise ValueError(f'{value.name}: requested export UV layer is missing')
        originals={value:value.data for value in values}
        bindings=capture(values)
        report=[{'object':value.name,'source_layer':name,
                 'source_index':list(value.data.uv_layers.keys()).index(name),
                 'export_index':None if primary else 0,
                 **({'export_primvar':primary} if primary else {}),
                 'source_layers':[name,*[u.name for u in value.data.uv_layers if u.name!=name]],
                 'layers':labels(value.data.uv_layers.keys(),name,primary)}
                for value in values]
    copies={}
    try:
        for value,original in originals.items():
            if original not in copies:
                copy=original.copy()
                copies[original]=copy
                copy.use_fake_user=False
                reorder(copy,name,primary)
            value.data=copies[original]
        bpy.context.view_layer.update()
        yield report
    finally:
        for value,original in originals.items():value.data=original
        restore(bindings)
        for copy in copies.values():bpy.data.meshes.remove(copy)
        bpy.context.view_layer.update()
