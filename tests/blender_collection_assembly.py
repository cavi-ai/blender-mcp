"""Native assembly geometry, temporary-ID cleanup and editable save/reopen checks."""

import json
import os
import runpy
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import bpy
from mathutils.kdtree import KDTree

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from cavi_blender_mcp import blender_assembly
from cavi_blender_mcp import blender_bridge as bridge
from cavi_blender_mcp.blender_asset_library import ids


def points(objects):
    return [value.matrix_world @ vertex.co for value in objects for vertex in value.data.vertices]


def distance(left, right):
    tree = KDTree(len(right))
    for index, point in enumerate(right):
        tree.insert(point, index)
    tree.balance()
    return max(tree.find(point)[2] for point in left)


with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
    bridge._workspace = root
    os.environ['CAVI_BLENDER_WORKSPACE'] = str(root)
    runpy.run_path(str(Path(__file__).with_name('collection_assembly_fixture.py')))
    bpy.ops.wm.save_as_mainfile(filepath=str(root/'baseline.blend'))
    state = bridge.dispatch('session_control', {'action': 'inspect'})
    lease = bridge.dispatch('session_control', {'action': 'claim', 'owner': 'assembly-check',
        'expected_project': state['project_id']})['lease_id']

    def edit(operation, **params):
        return bridge.dispatch('owned_edit', {'operation': operation, 'params': {**params, 'lease_id': lease}})

    source = bridge.dispatch('inspect_asset_library', {'path': 'kit.blend'})
    loaded = edit('append_asset_library_instances', path='kit.blend', names=['GardenKit'],
                  expected_sha256=source['sha256'])
    first = loaded['instances'][0]['name']
    edit('transform_object', name=first, location=[2, 1, 0], rotation_degrees=[0, 0, 90])
    edit('duplicate_object', name=first, new_name='GardenKit_B', linked=True)
    edit('transform_object', name='GardenKit_B', location=[-3, -1, 2],
         rotation_degrees=[15, 0, 40], scale=[-1.2, .8, 1.1])
    names = [first, 'GardenKit_B']
    context = (bpy.data.filepath, bpy.context.scene, set(bpy.context.selected_objects), bpy.context.view_layer.objects.active)
    before = ids()
    matrix = bpy.data.objects[first].matrix_basis.copy()
    try:
        edit('transform_object', name=first, location=[99, 99, 99], scale=[1, 0, 1])
    except ValueError:
        pass
    else:
        raise AssertionError('Zero scale succeeded')
    assert bpy.data.objects[first].matrix_basis == matrix
    bpy.context.view_layer.update()
    # Independent reference: every visible mesh instance in this fixture, including nested leaves.
    expected, leaves = [], 0
    for instance in bpy.context.evaluated_depsgraph_get().object_instances:
        if instance.is_instance and instance.show_self and instance.object.type == 'MESH':
            expected.extend(instance.matrix_world @ v.co for v in instance.object.data.vertices)
            leaves += 1
    assert leaves == 6
    errors = {}
    for extension in ['glb', 'fbx']:
        report = edit('export_assembly', path='garden.'+extension, names=names)
        assert report['triangles'] == 120 and report['unique_meshes'] == 3, report
        assert ids() == before
        assert context == (bpy.data.filepath, bpy.context.scene, set(bpy.context.selected_objects), bpy.context.view_layer.objects.active)
        edit('import_mesh' if extension == 'glb' else 'import_fbx', path='garden.'+extension, name='Checked')
        bpy.context.view_layer.update()
        created = ids()-before
        imported = [v for v in created if isinstance(v, bpy.types.Object) and v.type == 'MESH']
        actual = points(imported)
        error = max(distance(expected, actual), distance(actual, expected))
        assert error < .00001, (extension, error)
        assert all(v.data.materials[p.material_index]
                   and v.data.materials[p.material_index].name.startswith('Blue')
                   for v in imported for p in v.data.polygons)
        errors[extension] = error
        bpy.data.batch_remove(ids=tuple(created))
    # An exporter failure must remove both temporary proxies and the reserved output.
    with patch.object(blender_assembly, 'write', side_effect=RuntimeError('export failure')):
        try:
            edit('export_assembly', path='failed.glb', names=names)
        except RuntimeError:
            pass
        else:
            raise AssertionError('Exporter failure did not propagate')
    assert ids() == before and not (root/'failed.glb').exists()
    multiple = edit('append_asset_library_instances', path='kit.blend',
                    names=['GardenKit', 'TrimDefinition'], expected_sha256=source['sha256'])
    assert len(multiple['instances']) == 2, multiple
    assert all(i['name'] in bpy.context.scene.objects for i in multiple['instances'])
    bpy.data.batch_remove(ids=tuple(ids()-before))
    assert bridge.dispatch('inspect_asset_library', {'path': 'kit.blend'})['sha256'] == source['sha256']
    edit('save_project', path='consumer.blend')
    bpy.ops.wm.open_mainfile(filepath=str(root/'consumer.blend'))
    collection = bpy.data.objects[first].instance_collection
    assert bpy.data.objects['GardenKit_B'].instance_collection == collection
    assert collection not in bpy.context.scene.collection.children[:]
    assert bpy.data.objects['Fence'].modifiers[0].type == 'NODES'
    print(json.dumps({'blender': bpy.app.version_string, 'mesh_placements': leaves,
        'roundtrip_max_error_m': errors, 'failed_export_cleaned': True,
        'source_context_preserved': True, 'shared_editable_instances_reopened': True,
        'zero_scale_rejected_without_mutation': True}))
