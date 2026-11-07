"""Bind an existing finish to source polygons without rebuilding mesh data."""
import bpy

from .blender_bridge import editable_mesh, info
from .blender_errors import preflight
from .blender_material_bindings import capture, restore
from .blender_mesh_regions import mesh_digest, page_source
from .mesh_regions import fingerprint, indices


def assign(p):
    with preflight():
        value,_,_=page_source({'name':p.get('name'),'limit':1})
        editable_mesh(value.name)
        mesh=value.data
        if not value.is_editable or not mesh.is_editable:
            raise ValueError('Use an editable working copy before assigning source-face materials')
        faces=sorted(indices(p.get('face_indices'),len(mesh.polygons)))
        before=mesh_digest(mesh)
        fingerprint(p.get('expected_mesh_sha256'),before)
        matches=[m for m in bpy.data.materials if m.name==p.get('material_name')]
        if len(matches)!=1:
            raise ValueError('Existing material name must identify exactly one finish')
        material=matches[0]
        slots=[i for i,s in enumerate(value.material_slots) if s.material==material]
        slot=slots[0] if slots else len(value.material_slots)
        if slot>bpy.types.MeshPolygon.bl_rna.properties['material_index'].hard_max:
            raise ValueError('No additional polygon material index is available')
        selected=set(faces)
        if not slots and any(f.material_index==slot and f.index not in selected for f in mesh.polygons):
            raise ValueError('Appending this slot would bind unselected faces; include them or repair their indices')
        previous=[mesh.polygons[i].material_index for i in faces]
        changed=sum(old!=slot for old in previous)
        summary={'face_indices':faces,'material':material.name,'slot':slot,
            'slot_created':not slots,'changed_faces':changed,'previous_slots':previous,
            'mesh_sha256_before':before}
        snapshot=capture([value])
    try:
        if not slots:
            mesh.materials.append(material)
        if changed:
            for index in faces:
                mesh.polygons[index].material_index=slot
            mesh.update()
        summary['mesh_sha256_after']=mesh_digest(mesh)
        return {**info(value),'face_material':summary}
    except Exception:
        for index,old in zip(faces,previous,strict=True):
            mesh.polygons[index].material_index=old
        restore(snapshot)
        mesh.update()
        raise
