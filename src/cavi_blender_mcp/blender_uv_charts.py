"""Read chart membership and exact source UV identity without editing scene state."""
import hashlib
import struct
import sys
from array import array
from collections import Counter

from .uv_layout import MAX_TRIANGLES, face_charts


def uv_digest(layer):
    digest = hashlib.sha256(b'cavi-source-uv-v1\0' + layer.name.encode() + b'\0')
    values = array('f', [0]) * (len(layer.data)*2)
    layer.data.foreach_get('uv', values)
    if sys.byteorder != 'little':
        values.byteswap()
    pins = array('b', [0]) * len(layer.data)
    layer.data.foreach_get('pin_uv', pins)
    digest.update(struct.pack('<Q', len(layer.data)) + values.tobytes() + pins.tobytes())
    return digest.hexdigest()


def face_page(mesh, name, faces):
    layer = mesh.uv_layers.get(name)
    if layer is None:
        raise ValueError('Requested UV layer is missing')
    if len(mesh.loops) > MAX_TRIANGLES*3:
        raise ValueError('Chart inspection exceeds the 60000 source-loop budget')
    mesh.calc_loop_triangles()
    labels = face_charts([[tuple(layer.data[i].uv) for i in t.loops] for t in mesh.loop_triangles],
                         [list(t.vertices) for t in mesh.loop_triangles],
                         [t.polygon_index for t in mesh.loop_triangles])
    counts = Counter(labels.values())
    rows = {}
    for face in faces:
        uv = [layer.data[i] for i in face.loop_indices]
        rows[face.index] = {'chart': labels[face.index], 'chart_faces': counts[labels[face.index]],
            'bounds': [[min(p.uv[axis] for p in uv) for axis in (0, 1)],
                       [max(p.uv[axis] for p in uv) for axis in (0, 1)]],
            'pinned_loops': sum(p.pin_uv for p in uv)}
    return {'layer': layer.name, 'sha256': uv_digest(layer), 'charts': len(counts)}, rows
