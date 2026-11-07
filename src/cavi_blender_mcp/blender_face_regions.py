"""Read connected source polygons without changing native selection or mesh data."""
import hashlib
import json
import math

from .blender_errors import preflight
from .blender_mesh_regions import mesh_digest, page_source
from .blender_uv_charts import uv_digest
from .face_regions import component
from .uv_layout import uv_edge_key


def inspect(p):
    with preflight():
        value,limit,offset=page_source(p)
        mesh=value.data
        query=p.get('region',{})
        seed=query.get('seed')
        if type(seed) is not int or not 0<=seed<len(mesh.polygons):
            raise ValueError('region.seed must identify a current source face')
        stops=query.get('stop_at',[])
        if (not isinstance(stops,list) or any(s not in ('seam','material','uv') for s in stops)
                or len(set(stops))!=len(stops)):
            raise ValueError('region.stop_at requires unique seam/material/uv boundaries')
        layer=None
        if 'uv' in stops:
            layer=mesh.uv_layers.get(p.get('uv_layer') or '')
            if layer is None:
                raise ValueError('UV boundaries require an existing explicit uv_layer')
        elif p.get('uv_layer') is not None:
            raise ValueError('uv_layer requires a UV boundary')
        uv={'layer':layer.name,'sha256':uv_digest(layer)} if layer is not None else None
        angle=query.get('angle_limit_degrees')
        if angle is not None and (type(angle) not in (float,int) or not math.isfinite(angle) or not 0<=angle<=180):
            raise ValueError('region angle must be finite degrees from 0 to 180')
        digest=mesh_digest(mesh)
        edge_faces=[[] for _ in mesh.edges]
        edge_uvs=[[] for _ in mesh.edges] if layer is not None else None
        for face in mesh.polygons:
            for loop in face.loop_indices:
                edge=mesh.loops[loop].edge_index
                edge_faces[edge].append(face.index)
                if layer is not None:
                    following=face.loop_start+(loop-face.loop_start+1)%face.loop_total
                    edge_uvs[edge].append(uv_edge_key(
                        (mesh.loops[loop].vertex_index,*layer.data[loop].uv),
                        (mesh.loops[following].vertex_index,*layer.data[following].uv)))
        blocked=set()
        for edge,linked in zip(mesh.edges,edge_faces,strict=True):
            if len(linked)!=2:
                continue
            first,second=(mesh.polygons[i] for i in linked)
            if (('seam' in stops and edge.use_seam)
                    or ('material' in stops and first.material_index!=second.material_index)
                    or (edge_uvs is not None and edge_uvs[edge.index][0]!=edge_uvs[edge.index][1])):
                blocked.add(edge.index)
            elif angle is not None:
                a,b=first.normal,second.normal
                length=a.length*b.length
                if length==0 or math.degrees(math.acos(max(-1.,min(1.,a.dot(b)/length))))>angle+1e-6:
                    blocked.add(edge.index)
        selected=component(seed,len(mesh.polygons),edge_faces,blocked)
        identity={'mesh_sha256':digest,'seed':seed,'stop_at':sorted(stops),
                  'angle_limit_degrees':angle,'faces':selected}
        if uv is not None:
            identity['uv']=uv
        selection_hash=hashlib.sha256(b'cavi-source-face-region-v1\0'+json.dumps(identity,sort_keys=True,
                                    separators=(',',':')).encode()).hexdigest()
        result={'name':value.name,'type':'MESH','mesh':mesh.name,'scope':'source_face_region',
            'mesh_sha256':digest,'total':len(selected),'offset':offset,'limit':limit,
            'faces':[{'index':i} for i in selected[offset:offset+limit]],
            'region':{'seed':seed,'stop_at':sorted(stops),'angle_limit_degrees':angle,
                      'selection_sha256':selection_hash,'nonmanifold_edges':'stop'}}
        if uv is not None:
            result['uv']=uv
        return result
