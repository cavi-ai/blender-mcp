"""Object-only removal after checking the complete scene and dependency boundary."""
import json

import bpy

from .blender_errors import preflight
from .operations import MAX_RESPONSE_BYTES


def delete(p):
    with preflight():
        if bpy.context.mode!='OBJECT':
            raise ValueError('Delete objects in Object Mode')
        recursive=p.get('recursive',False)
        if type(recursive) is not bool:
            raise ValueError('recursive must be boolean')
        scene=bpy.context.scene
        matches=[value for value in scene.objects if value.name==p['name']]
        if not matches:
            raise ValueError('Object does not exist in the current scene')
        if len(matches)!=1:
            raise ValueError('Object name is ambiguous in the current scene')
        root=matches[0]
        children={}
        for value in bpy.data.objects:
            children.setdefault(value.parent,[]).append(value)
        if children.get(root) and not recursive:
            raise ValueError('Object has children; declare recursive=true to delete the hierarchy')
        targets={root}
        pending=list(children.get(root,[])) if recursive else []
        while pending:
            value=pending.pop()
            if value not in targets:
                targets.add(value)
                pending.extend(children.get(value,[]))
        other_objects={value for other in bpy.data.scenes if other!=scene for value in other.objects}
        if targets & other_objects:
            raise ValueError('Deletion includes an object used by another scene')
        if any(scene.objects.get(value.name)!=value for value in targets):
            raise ValueError('Deletion includes an object outside the current scene')
        collections=set()
        pending=[scene.collection]
        while pending:
            value=pending.pop()
            if value not in collections:
                collections.add(value)
                pending.extend(value.children)
        definitions={}
        for value in bpy.data.objects:
            collection=value.instance_collection if value.instance_type=='COLLECTION' else None
            if value not in targets and collection is not None:
                if collection not in definitions:
                    definitions[collection]=set(collection.all_objects)
                if targets & definitions[collection]:
                    raise ValueError('Object is part of an instanced collection; delete the placement or make it unique')
        users=bpy.data.user_map(subset=tuple(targets))
        for value in targets:
            for user in users.get(value,set()):
                if user in targets:
                    continue
                if user in collections:
                    membership=int(user.objects.get(value.name)==value)
                    if user.user_of_id(value)<=membership:
                        continue
                if user==scene:
                    # Scene users include per-view-layer bases, not just master links.
                    membership=int(scene.collection.objects.get(value.name)==value)+int(scene.camera==value)
                    membership+=sum(layer.objects.get(value.name)==value for layer in scene.view_layers)
                    if user.user_of_id(value)<=membership:
                        continue
                if isinstance(user,(bpy.types.Screen,bpy.types.WorkSpace,bpy.types.WindowManager)):
                    continue
                raise ValueError(f'External reference {user.name} uses {value.name}')
        names=sorted(value.name for value in targets)
        if len(set(names))!=len(names):
            raise ValueError('Hierarchy contains ambiguous object names')
        result={'name':root.name,'deleted':names,'count':len(names)}
        if len(json.dumps(result).encode())>MAX_RESPONSE_BYTES-4096:
            raise ValueError('Deletion receipt exceeds the transport budget')
    bpy.data.batch_remove(ids=tuple(targets))
    return result
