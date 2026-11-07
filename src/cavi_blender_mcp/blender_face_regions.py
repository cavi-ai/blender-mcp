"""Read connected source polygons without changing native selection or mesh data."""
import hashlib
import json
import math

from .blender_errors import preflight
from .blender_mesh_regions import mesh_digest, page_source
from .face_regions import component


def inspect(p):
    with preflight():
        value,limit,offset=page_source(p)
        mesh=value.data
        query=p.get('region',{})
        seed=query.get('seed')
        if type(seed) is not int or not 0<=seed<len(mesh.polygons):
            raise ValueError('region.seed must identify a current source face')
        stops=query.get('stop_at',[])
        if (not isinstance(stops,list) or any(s not in ('seam','material') for s in stops)
                or len(set(stops))!=len(stops)):
            raise ValueError('region.stop_at requires unique seam/material boundaries')
        angle=query.get('angle_limit_degrees')
        if angle is not None and (type(angle) not in (float,int) or not math.isfinite(angle) or not 0<=angle<=180):
            raise ValueError('region angle must be finite degrees from 0 to 180')
        digest=mesh_digest(mesh)
        edge_faces=[[] for _ in mesh.edges]
        for face in mesh.polygons:
            for loop in face.loop_indices:
                edge_faces[mesh.loops[loop].edge_index].append(face.index)
        blocked=set()
        for edge,linked in zip(mesh.edges,edge_faces,strict=True):
            if len(linked)!=2:
                continue
            first,second=(mesh.polygons[i] for i in linked)
            if ('seam' in stops and edge.use_seam) or ('material' in stops and first.material_index!=second.material_index):
                blocked.add(edge.index)
            elif angle is not None:
                a,b=first.normal,second.normal
                length=a.length*b.length
                if length==0 or math.degrees(math.acos(max(-1.,min(1.,a.dot(b)/length))))>angle+1e-6:
                    blocked.add(edge.index)
        selected=component(seed,len(mesh.polygons),edge_faces,blocked)
        identity={'mesh_sha256':digest,'seed':seed,'stop_at':sorted(stops),
                  'angle_limit_degrees':angle,'faces':selected}
        selection_hash=hashlib.sha256(b'cavi-source-face-region-v1\0'+json.dumps(identity,sort_keys=True,
                                    separators=(',',':')).encode()).hexdigest()
        return {'name':value.name,'type':'MESH','mesh':mesh.name,'scope':'source_face_region',
            'mesh_sha256':digest,'total':len(selected),'offset':offset,'limit':limit,
            'faces':[{'index':i} for i in selected[offset:offset+limit]],
            'region':{'seed':seed,'stop_at':sorted(stops),'angle_limit_degrees':angle,
                      'selection_sha256':selection_hash,'nonmanifold_edges':'stop'}}
