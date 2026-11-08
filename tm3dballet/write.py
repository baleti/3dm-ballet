"""Guarded edit/save for .3dm. rhino3dm re-serializes the whole file, so identity is by semantic snapshot.
Gate: refuse on anything the library may drop (unreadable objects, plug-in data), write to a temp file,
re-read it, require snapshot equality except for the intended edit, keep a backup, replace atomically."""
import hashlib, json, os, shutil, tempfile
import rhino3dm as R
from . import probe

WRITE_TIMEOUT = 120

class Refused(Exception): pass

def _guarded_write(m, tmp, ver, timeout=120):
    """m.Write in a daemon thread so a native stall turns into Refused instead of a frozen save.
    (Only effective if the native call releases the GIL; if it does not, nothing in-process can help.)"""
    import threading
    box = {}
    def run():
        try: box['ok'] = m.Write(tmp, ver)
        except BaseException as e: box['err'] = e
    t = threading.Thread(target=run, daemon=True); t.start(); t.join(timeout)
    if t.is_alive(): raise Refused('write timed out after %ss' % timeout)
    if 'err' in box: raise Refused('write raised %s' % box['err'])
    return box.get('ok')

def _r(x): return round(float(x), 9)

def _fp(g):
    """structural fingerprint (Encode bytes are not canonical across rewrites, e.g. meshes); falls back to Encode hash"""
    ot = str(g.ObjectType).split('.')[-1]
    try:
        if ot == 'Mesh':
            return hashlib.sha1(repr(([(_r(v.X), _r(v.Y), _r(v.Z)) for v in g.Vertices], [tuple(f) for f in g.Faces],
                                      [(_r(v.X), _r(v.Y), _r(v.Z)) for v in g.Normals], [(_r(v.X), _r(v.Y)) for v in g.TextureCoordinates],
                                      [tuple(c) for c in g.VertexColors])).encode()).hexdigest()[:16]
        if ot == 'Curve':
            d = g.Domain; pts = [g.PointAt(d.T0 + (d.T1 - d.T0) * i / 32) for i in range(33)]
            return hashlib.sha1(repr((type(g).__name__, _r(d.T0), _r(d.T1), g.SpanCount, g.Degree, [(_r(p.X), _r(p.Y), _r(p.Z)) for p in pts])).encode()).hexdigest()[:16]
    except Exception:
        pass
    return _h(g)

def _h(o):
    try: s = json.dumps(o.Encode(), sort_keys=True, default=str)
    except Exception: s = repr(o)
    return hashlib.sha1(s.encode()).hexdigest()[:16]

def _pd(p):
    f = getattr(p, 'RdkXml', None)
    return hashlib.sha1((f() if callable(f) else type(p).__name__).encode()).hexdigest()[:12]

def _us(o):
    try: return sorted((str(k), str(v)) for k, v in o.GetUserStrings())
    except Exception: return ['unreadable']

def _doc_strings(m):
    # rhino3dm exposes only the count of document user text (no keys/values), so count is all we can compare
    try: return ['n=%d' % m.Strings.DocumentUserTextCount, 'len=%d' % len(m.Strings)]
    except Exception: return ['unreadable']

def _view(v):
    try:
        vp = v.Viewport; c = lambda p: (_r(p.X), _r(p.Y), _r(p.Z))
        return [v.Name, str(vp.Id), c(vp.CameraLocation), c(vp.CameraDirection), c(vp.CameraUp), bool(vp.IsParallelProjection),
                _r(vp.Camera35mmLensLength) if vp.IsPerspectiveProjection else 0.0, _us(vp), v.WallpaperName]
    except Exception:
        return ['unreadable', _h(v)]

def snapshot(m):
    """canonical, comparable description of a File3dm model (ids, geometry hashes, tables)"""
    objs = {}
    for i, o in enumerate(m.Objects):
        a = o.Attributes; g = o.Geometry
        objs[str(a.Id)] = {'type': str(g.ObjectType) if g is not None else None, 'geom': _fp(g) if g is not None else None,
                           'name': a.Name, 'layer': a.LayerIndex, 'color': [int(x) for x in a.ObjectColor], 'csrc': str(a.ColorSource),
                           'ustr': _us(a), 'gstr': _us(g) if g is not None else None, 'mat': a.MaterialIndex, 'visible': a.Visible, 'mode': str(a.Mode)}
    tab = lambda t, f: [f(x) for x in t]
    return {'version': m.ArchiveVersion, 'objects': objs, 'n_objects': len(m.Objects),
            'layers': tab(m.Layers, lambda l: [str(l.Id), l.Name, [int(x) for x in l.Color], str(l.ParentLayerId), l.GetPersistentVisibility(), _us(l)]),
            'materials': tab(m.Materials, lambda x: [str(x.Id), x.Name, [int(c) for c in x.DiffuseColor], x.Transparency]),
            'idefs': tab(m.InstanceDefinitions, lambda d: [str(d.Id), d.Name, sorted(str(i) for i in d.GetObjectIds())]),
            'groups': len(m.Groups), 'views': [_view(v) for v in m.Views], 'named_views': [_view(v) for v in m.NamedViews], 'linetypes': len(m.Linetypes), 'bitmaps': len(m.Bitmaps),
            'docstrings': _doc_strings(m),
            'units': str(m.Settings.ModelUnitSystem),
            'plugin': [_pd(p) for p in m.PlugInData],
            'rdk': hashlib.sha1(str(m.RdkXml()).encode()).hexdigest()[:12]}

def diff(a, b):
    """list of human-readable differences between two snapshots"""
    out = []
    for k in a:
        if k == 'objects': continue
        if a[k] != b[k]: out.append('%s differs' % k)
    for i in set(a['objects']) | set(b['objects']):
        x, y = a['objects'].get(i), b['objects'].get(i)
        if x is None or y is None: out.append('object %s %s' % (i, 'added' if x is None else 'removed')); continue
        for k in x:
            if x[k] != y[k]: out.append('object %s %s differs' % (i, k))
    return out

def gate(m):
    """reasons the library cannot be trusted to round-trip this model; empty = ok"""
    why = []
    if any(o.Geometry is None for o in m.Objects): why.append('unreadable object(s) would be dropped')
    if m.ArchiveVersion not in (50, 60, 70, 80): why.append('archive version %s not writable' % m.ArchiveVersion)
    return why

def edit_file(path, edit, expect, backup=True):
    """edit(model) mutates the model; expect(diffs) -> True when the diffs are exactly the intended ones.
    Original is replaced only if every check passes. Returns list of diffs applied."""
    path = os.path.realpath(path)   # never replace a symlink itself; edit its target in place of the link
    try: probe.probe(path)
    except probe.Unreadable as e: raise Refused(str(e))
    if os.stat(path).st_nlink > 1: raise Refused('file has multiple hard links; replacing it would silently detach the other names')
    st0 = os.stat(path); sig0 = (st0.st_size, st0.st_mtime_ns, hashlib.sha256(open(path, 'rb').read()).hexdigest())
    m = R.File3dm.Read(path)
    if m is None: raise Refused('unreadable')
    why = gate(m)
    if why: raise Refused('; '.join(why))
    before = snapshot(m); ver = m.ArchiveVersion
    edit(m)
    d = os.path.dirname(os.path.abspath(path))
    try: fd, tmp = tempfile.mkstemp(suffix='.3dm', dir=d); os.close(fd)
    except OSError as e: raise Refused('cannot create temp file next to source: %s' % e)
    try:
        if not _guarded_write(m, tmp, ver, WRITE_TIMEOUT): raise Refused('write failed')
        try: probe.probe(tmp)
        except probe.Unreadable as e: raise Refused('output ' + str(e))
        m2 = R.File3dm.Read(tmp)
        if m2 is None: raise Refused('output unreadable')
        after = snapshot(m2)
        if after['version'] != before['version']: raise Refused('archive version changed')
        ds = diff(before, after)
        if not expect(ds): raise Refused('unexpected differences: %s' % ds[:5])
        st1 = os.stat(path)
        if (st1.st_size, st1.st_mtime_ns, hashlib.sha256(open(path, 'rb').read()).hexdigest()) != sig0:
            raise Refused('source changed during edit; refusing to overwrite')
        if backup:
            try: shutil.copy2(path, path + '.bak')
            except OSError as e: raise Refused('backup failed, original untouched: %s' % e)
        try: os.replace(tmp, path)
        except OSError as e: raise Refused('replace failed, original untouched: %s' % e)
        return ds
    finally:
        if os.path.exists(tmp): os.remove(tmp)

def rename_layer(path, old, new):
    def edit(m):
        n = [l for l in m.Layers if l.Name == old]
        if len(n) != 1: raise Refused('layer %r found %d times' % (old, len(n)))
        n[0].Name = new
    return edit_file(path, edit, lambda ds: ds == ['layers differs'])
