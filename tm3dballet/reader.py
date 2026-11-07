"""Reader: contents summary and mesh extraction for .3dm via rhino3dm (openNURBS)."""
import collections
import numpy as np
from . import glb
import rhino3dm as R

# metres per model unit (subset; others fall back to 1.0 and are reported)
_UNITS = {'None': 1.0, 'Millimeters': .001, 'Centimeters': .01, 'Meters': 1.0, 'Kilometers': 1000.0, 'Microns': 1e-6,
          'Inches': .0254, 'Feet': .3048, 'Yards': .9144, 'Miles': 1609.344}

def load(path):
    m = R.File3dm.Read(path)
    if m is None: raise ValueError('not a readable .3dm file: %s' % path)
    return m

def unit_scale(m):
    n = str(m.Settings.ModelUnitSystem).split('.')[-1]
    return _UNITS.get(n, 1.0), n

def info(path):
    m = load(path); sc, un = unit_scale(m)
    types = collections.Counter(str(o.Geometry.ObjectType).split('.')[-1] if o.Geometry is not None else 'Unknown' for o in m.Objects)
    return {'file': path, 'archive_version': m.ArchiveVersion, 'application': m.ApplicationName, 'units': un, 'objects': len(m.Objects),
            'types': dict(types), 'layers': [l.Name for l in m.Layers], 'materials': len(m.Materials), 'groups': len(m.Groups),
            'instance_definitions': len(m.InstanceDefinitions), 'views': len(m.Views), 'named_views': len(m.NamedViews),
            'bitmaps': len(m.Bitmaps), 'embedded_files': len(m.EmbeddedFiles), 'linetypes': len(m.Linetypes), 'dimstyles': len(m.DimStyles)}

def _mesh_tris(mesh):
    v = np.array([(p.X, p.Y, p.Z) for p in mesh.Vertices], float).reshape(-1, 3); t = []
    for f in mesh.Faces:
        a, b, c, d = f
        t.append((a, b, c))
        if d != c: t.append((a, c, d))
    return v, np.array(t, np.int64).reshape(-1, 3)

def _geom_meshes(g):
    """list of rhino meshes for a geometry, [] if none stored"""
    ot = str(g.ObjectType).split('.')[-1]
    if ot == 'Mesh': return [g]
    out = []
    if ot == 'Brep':
        for f in g.Faces:
            mm = f.GetMesh(R.MeshType.Any)
            if mm is not None: out.append(mm)
    elif ot == 'Extrusion':
        mm = g.GetMesh(R.MeshType.Any)
        if mm is not None: out.append(mm)
    return out

def _wire(g, n=24):
    """polyline samples for curves and (edge fallback) breps; list of Nx3 arrays"""
    ot = str(g.ObjectType).split('.')[-1]
    cs = []
    if ot == 'Curve': cs = [g]
    elif ot == 'Brep': cs = [e for e in g.Edges]
    elif ot == 'Extrusion':
        b = g.ToBrep(True)
        cs = [e for e in b.Edges] if b is not None else []
    out = []
    for c in cs:
        d = c.Domain; k = max(2, n * max(1, c.SpanCount) if not c.IsLinear() else 2)
        pts = [c.PointAt(d.T0 + (d.T1 - d.T0) * i / (k - 1)) for i in range(k)]
        out.append(np.array([(p.X, p.Y, p.Z) for p in pts], float))
    return out

def to_glb(path, out):
    """Export all visible objects. Returns stats dict. Solids use stored render meshes; objects without
    a stored mesh are drawn as wireframe (rhino3dm cannot mesh); points are skipped."""
    m = load(path); sc, un = unit_scale(m)
    yup = lambda v: np.c_[v[:, 0], v[:, 2], -v[:, 1]] * sc
    layer_col = {i: l.Color for i, l in enumerate(m.Layers)}
    batches = {}; st = collections.Counter()
    for oi, o in enumerate(m.Objects):
        g, a = o.Geometry, o.Attributes
        if g is None: st['unreadable'] += 1; continue
        if not a.Visible: st['hidden'] += 1; continue
        li = a.LayerIndex; lay = m.Layers[li] if 0 <= li < len(m.Layers) else None
        if lay is not None and not lay.GetPersistentVisibility(): st['layer_hidden'] += 1; continue
        c = a.ObjectColor if int(a.ColorSource) == 1 else (lay.Color if lay is not None else (200, 200, 200, 255))
        col = (c[0] / 255, c[1] / 255, c[2] / 255, 1.0)
        meshes = _geom_meshes(g)
        if meshes:
            for mm in meshes:
                v, t = _mesh_tris(mm)
                if len(t): _add(batches, (li, col, 4), v, t.ravel(), oi, yup); st['meshed'] += 1
        else:
            w = _wire(g)
            for p in w:
                idx = np.array([(i, i + 1) for i in range(len(p) - 1)]).ravel()
                _add(batches, (li, col, 1), p, idx, oi, yup)
            st['wire' if w else 'skipped_' + str(g.ObjectType).split('.')[-1]] += 1
    out_b = []
    for (li, col, mode), b in sorted(batches.items(), key=lambda kv: (kv[0][0], kv[0][2])):
        name = (m.Layers[li].Name if 0 <= li < len(m.Layers) else 'none') + ('' if mode == 4 else ' (wire)')
        out_b.append({'name': name, 'color': col, 'mode': mode, 'pos': np.vstack(b['pos']), 'eidx': np.concatenate(b['ei']), 'idx': np.concatenate(b['ix'])})
    glb.write_glb(out, out_b)
    st['batches'] = len(out_b); st['units'] = un
    return dict(st)

def _add(batches, key, v, ix, oi, yup):
    b = batches.setdefault(key, {'pos': [], 'ei': [], 'ix': [], 'n': 0})
    b['pos'].append(yup(v)); b['ei'].append(np.full(len(v), oi, np.float32)); b['ix'].append(np.asarray(ix, np.int64) + b['n']); b['n'] += len(v)
