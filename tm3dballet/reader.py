"""Reader: contents summary and mesh extraction for .3dm via rhino3dm (openNURBS)."""
import collections
import numpy as np
from . import glb, tess
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

def _geom_vt(g):
    """[(verts, tris)] for a geometry and whether some faces could not be meshed"""
    ot = str(g.ObjectType).split('.')[-1]
    if ot != 'Brep':
        return [_mesh_tris(mm) for mm in _geom_meshes(g) if len(mm.Faces)], False
    out = []; partial = False
    for f in g.Faces:
        mm = f.GetMesh(R.MeshType.Any)
        if mm is not None:
            v, t = _mesh_tris(mm)
            if len(t): out.append((v, t)); continue
        try: r = tess.tess_face(g, f)
        except Exception: r = None
        if r is None: partial = True
        else: out.append(r)
    return out, partial

_MARKER_TYPES = ('Point', 'TextDot', 'PointSet', 'PointCloud')

def _markers(g, ot, h):
    """3-axis crosses (as line strips) at point-like geometry; PointCloud capped at 2000 points"""
    try:
        if ot == 'PointCloud':
            n = g.Count; step = max(1, n // 2000)
            pts = [g[i] if hasattr(g, '__getitem__') else None for i in range(0, n, step)]
            pts = [(p.X, p.Y, p.Z) for p in pts if p is not None]
        else:
            c = g.GetBoundingBox().Center; pts = [(c.X, c.Y, c.Z)]
    except Exception:
        return []
    out = []
    for x, y, z in pts:
        for d in ((h, 0, 0), (0, h, 0), (0, 0, h)):
            out.append(np.array([(x - d[0], y - d[1], z - d[2]), (x + d[0], y + d[1], z + d[2])], float))
    return out

def _msize(m):
    d = 0.0
    for o in m.Objects:
        try:
            if o.Geometry is not None and str(o.Geometry.ObjectType).split('.')[-1] not in _MARKER_TYPES:
                d = max(d, o.Geometry.GetBoundingBox().Diagonal.Length)
        except Exception: pass
    return (d if d > 0 else 100.0) * 0.004

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

MAX_DEPTH = 16

def layer_visible(m, lay):
    """persistent visibility of a layer and all its ancestors (cycle-safe)"""
    ids = {str(getattr(l, 'Id', i)): l for i, l in enumerate(m.Layers)}; seen = set()
    while lay is not None and id(lay) not in seen:
        if not lay.GetPersistentVisibility(): return False
        seen.add(id(lay)); lay = ids.get(str(getattr(lay, 'ParentLayerId', None)))
    return True

def _material_col(m, a, lay, col):
    """diffuse colour and transparency from the object (or layer) render material, if any"""
    try:
        src = str(a.MaterialSource).split('.')[-1]
        idx = a.MaterialIndex if src == 'MaterialFromObject' else (lay.RenderMaterialIndex if src == 'MaterialFromLayer' and lay is not None else -1)
        if 0 <= idx < len(m.Materials):
            mt = m.Materials[idx]; d = mt.DiffuseColor
            return (d[0] / 255, d[1] / 255, d[2] / 255, max(0.05, min(1.0, 1.0 - float(mt.Transparency))))
    except Exception:
        pass
    return col

def _mat(t):
    return np.array(t.ToFloatArray(True), float).reshape(4, 4)

def _mul(a, b):
    return b if a is None else a @ b

def to_glb(path, out):
    """Export all visible objects. Returns stats dict. Solids use stored render meshes; objects without
    a stored mesh are drawn as wireframe (rhino3dm cannot mesh); points are skipped."""
    m = load(path); sc, un = unit_scale(m)
    yup = lambda v: np.c_[v[:, 0], v[:, 2], -v[:, 1]] * sc
    layer_col = {i: l.Color for i, l in enumerate(m.Layers)}
    batches = {}; st = collections.Counter()
    msize = _msize(m)
    by_id = {}; idefs = {}
    for o in m.Objects:
        try: by_id[str(o.Attributes.Id)] = o
        except Exception: pass
    for d in m.InstanceDefinitions:
        try: idefs[str(d.Id)] = [str(i) for i in d.GetObjectIds()]
        except Exception: pass
    def emit(o, oi, xf, depth):
        g, a = o.Geometry, o.Attributes
        if g is None: st['unreadable'] += 1; return
        if not a.Visible: st['hidden'] += 1; return
        li = a.LayerIndex; lay = m.Layers[li] if 0 <= li < len(m.Layers) else None
        if lay is not None and not layer_visible(m, lay): st['layer_hidden'] += 1; return
        ot = str(g.ObjectType).split('.')[-1]
        if ot == 'InstanceReference':
            ids = idefs.get(str(g.ParentIdefId))
            if ids is None or depth >= MAX_DEPTH: st['instance_unresolved'] += 1; return
            st['instances'] += 1
            for i in ids:
                mo = by_id.get(i)
                if mo is not None: emit(mo, oi, _mul(xf, _mat(g.Xform)), depth + 1)
            return
        c = a.ObjectColor if int(a.ColorSource) == 1 else (lay.Color if lay is not None else (200, 200, 200, 255))
        col = (c[0] / 255, c[1] / 255, c[2] / 255, 1.0)
        col = _material_col(m, a, lay, col)
        T = (lambda v: v) if xf is None else (lambda v: v @ xf[:3, :3].T + xf[:3, 3])
        vt, partial = _geom_vt(g)
        for v, t in vt:
            _add(batches, (li, col, 4), T(v), t.ravel(), oi, yup); st['meshed'] += 1
        if not vt or partial:
            w = _wire(g) if ot not in _MARKER_TYPES else _markers(g, ot, msize)
            for p in w:
                idx = np.array([(i, i + 1) for i in range(len(p) - 1)]).ravel()
                _add(batches, (li, col, 1), T(p), idx, oi, yup)
            if not vt: st['wire' if w else 'skipped_' + ot] += 1
            else: st['partial_wire'] += 1
    for oi, o in enumerate(m.Objects):
        if o.Attributes is not None and str(o.Attributes.Mode).split('.')[-1] == 'InstanceDefinitionObject': st['idef_member'] += 1; continue
        emit(o, oi, None, 0)
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
