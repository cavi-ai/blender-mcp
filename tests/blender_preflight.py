"""Native validation is rejected explicitly; failures after editing stay unmarked."""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from blender_skin_transfer import bpy, edit, options, rig, scene

from cavi_blender_mcp.blender_errors import PreflightRejected

objects, meshes, actions = set(bpy.data.objects), set(bpy.data.meshes), set(bpy.data.actions)
try:
    edit('transfer_skin_weights', **{**options, 'max_distance_m': 1e-9}, new_name='RejectedSkin')
except PreflightRejected:
    pass
else:
    raise AssertionError('Known transfer validation was not marked rejected')
assert objects == set(bpy.data.objects) and meshes == set(bpy.data.meshes)
assert actions == set(bpy.data.actions)
for operation, params in (
    ('bake_rig', {'name': 'Rig', 'new_name': 'Rig', 'action_name': 'Collision',
                  'start_frame': 1, 'end_frame': 2}),
    ('retarget_rig', {'name': 'Rig', 'source': 'Missing', 'source_action': 'Missing',
                      'action_name': 'Retarget'})):
    try:
        edit(operation, **params)
    except PreflightRejected:
        pass
    else:
        raise AssertionError('Known rig validation was not marked rejected')
assert actions == set(bpy.data.actions)
parent = bpy.data.objects.new('ShearParent', None)
scene.collection.objects.link(parent)
parent.scale = (2, 1, 1)
shear = rig.copy()
shear.data = rig.data.copy()
shear.name = 'ShearedRig'
shear.parent = parent
shear.rotation_mode = 'XYZ'
shear.rotation_euler.z = math.pi/4
scene.collection.objects.link(shear)
bpy.context.view_layer.update()
try:
    edit('bake_rig', name='ShearedRig', new_name='ShearedBake', action_name='ShearedClip',
         start_frame=1, end_frame=2)
except PreflightRejected as exc:
    raise AssertionError('Post-edit failure was incorrectly marked rejected') from exc
except ValueError as exc:
    assert 'shear' in str(exc).lower(), exc
else:
    raise AssertionError('Unrepresentable shear was accepted')
assert 'ShearedBake' not in bpy.data.objects and 'ShearedClip' not in bpy.data.actions
print('Native preflight boundaries: no-edit failures rejected; post-edit shear remains unmarked')
