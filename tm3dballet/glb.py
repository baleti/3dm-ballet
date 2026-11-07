"""Minimal GLB writer, same conventions as rvt-ballet (per-batch mesh, custom _EIDX attribute, y-up metres)."""
import json, struct
import numpy as np

def _lin(c): return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

def write_glb(path, batches):
    """batches: list of dict(name, color (r,g,b,a 0..1), mode 4|1, pos Nx3 (y-up m), eidx N, idx flat)"""
    parts, views, accs, meshes, mats, nodes = [], [], [], [], [], []
    off = 0
    def add(a, target):
        nonlocal off
        b = a.tobytes(); pad = (-len(b)) % 4
        views.append({'buffer': 0, 'byteOffset': off, 'byteLength': len(b), 'target': target})
        parts.append(b + b'\0' * pad); off += len(b) + pad
        return len(views) - 1
    for i, b in enumerate(batches):
        ix = np.ascontiguousarray(b['idx'], np.uint32)
        if len(ix) == 0: continue
        pos = np.ascontiguousarray(b['pos'], np.float32); ei = np.ascontiguousarray(b['eidx'], np.float32)
        pa = len(accs); accs.append({'bufferView': add(pos, 34962), 'componentType': 5126, 'count': len(pos), 'type': 'VEC3', 'min': pos.min(0).tolist(), 'max': pos.max(0).tolist()})
        ea = len(accs); accs.append({'bufferView': add(ei, 34962), 'componentType': 5126, 'count': len(ei), 'type': 'SCALAR'})
        ia = len(accs); accs.append({'bufferView': add(ix, 34963), 'componentType': 5125, 'count': len(ix), 'type': 'SCALAR'})
        c = b['color']
        mats.append({'name': b['name'], 'pbrMetallicRoughness': {'baseColorFactor': [_lin(x) for x in c[:3]] + [c[3]], 'metallicFactor': 0.0, 'roughnessFactor': 0.85}, 'doubleSided': True,
                     **({'alphaMode': 'BLEND'} if c[3] < 1 else {})})
        meshes.append({'name': b['name'], 'primitives': [{'attributes': {'POSITION': pa, '_EIDX': ea}, 'indices': ia, 'material': len(mats) - 1, 'mode': b.get('mode', 4)}]})
        nodes.append({'mesh': len(meshes) - 1, 'name': b['name']})
    binb = b''.join(parts)
    g = {'asset': {'version': '2.0', 'generator': '3dm-ballet'}, 'scene': 0, 'scenes': [{'nodes': list(range(len(nodes)))}], 'nodes': nodes, 'meshes': meshes,
         'materials': mats, 'accessors': accs, 'bufferViews': views, 'buffers': [{'byteLength': len(binb)}]}
    js = json.dumps(g, separators=(',', ':')).encode(); js += b' ' * ((-len(js)) % 4)
    with open(path, 'wb') as f:
        f.write(struct.pack('<4sII', b'glTF', 2, 12 + 8 + len(js) + 8 + len(binb)))
        f.write(struct.pack('<I4s', len(js), b'JSON') + js + struct.pack('<I4s', len(binb), b'BIN\0') + binb)
