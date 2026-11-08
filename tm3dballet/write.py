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

def _canon_xml(x):
    """attribute order is not significant in XML (the library re-serialises RDK XML with different attribute order);
    compare the parsed tree with attributes sorted. Unparseable text falls back to the raw string."""
    import xml.etree.ElementTree as ET
    try:
        def n(e): return [e.tag, sorted(e.attrib.items()), (e.text or '').strip(), (e.tail or '').strip(), [n(c) for c in e]]
        return repr(n(ET.fromstring(x.encode('utf-8', 'surrogatepass') if isinstance(x, str) else x)))
    except Exception:
        return x

def _pd(p):
    f = getattr(p, 'RdkXml', None)
    return hashlib.sha1(_canon_xml(f() if callable(f) else type(p).__name__).encode('utf-8', 'surrogatepass')).hexdigest()[:12]

def _us(o):
    try: return sorted((str(k), str(v)) for k, v in o.GetUserStrings())
    except Exception: return ['unreadable']

def _doc_strings(m):
    # rhino3dm exposes only the count of document user text (no keys/values), so count is all we can compare
    try: return ['n=%d' % m.Strings.DocumentUserTextCount(), 'len=%d' % len(m.Strings)]
    except Exception: return ['unreadable']

def _view(v):
    try:
        vp = v.Viewport; c = lambda p: (_r(p.X), _r(p.Y), _r(p.Z))
        return [v.Name, str(vp.Id), c(vp.CameraLocation), c(vp.CameraDirection), c(vp.CameraUp), bool(vp.IsParallelProjection),
                _r(vp.Camera35mmLensLength) if vp.IsPerspectiveProjection else 0.0, _us(vp), v.WallpaperName]
    except Exception:
        return ['unreadable', _h(v)]

def _g(f, d='?'):
    try: return f()
    except Exception: return d

def _lt(x): return [str(x.Id), x.Name, x.SegmentCount, _r(x.PatternLength), [str(x.GetSegment(i)) for i in range(x.SegmentCount)] if x.SegmentCount < 64 else '?', _us(x)]

def _extra(m):
    st = m.Settings
    # NOTE: touching Linetype objects segfaults/aborts rhino3dm at interpreter exit (wrapper lifetime bug), so only len() is used
    return {'linetypes_n': len(m.Linetypes),
            'groups': [_g(lambda x=x: [str(x.Id), x.Name, _us(x)]) for x in m.Groups],
            'bitmaps': [_g(lambda x=x: [str(x.Id), x.Width, x.Height, x.BitsPerPixel, x.SizeOfImage, _h(x)]) for x in m.Bitmaps],
            'dimstyles': [_g(lambda x=x: [x.Name, _us(x)]) for x in m.DimStyles],
            'tol': _g(lambda: [_r(st.ModelAbsoluteTolerance), _r(st.ModelAngleToleranceRadians), _r(st.ModelRelativeTolerance),
                               _r(st.PageAbsoluteTolerance), str(st.PageUnitSystem), [_r(c) for c in (st.ModelBasePoint.X, st.ModelBasePoint.Y, st.ModelBasePoint.Z)]])}

def _layer(l):
    return [str(l.Id), l.Name, [int(x) for x in l.Color], str(l.ParentLayerId), l.GetPersistentVisibility(), _us(l),
            _g(lambda: l.GetPersistentLocking()), _g(lambda: l.LinetypeIndex), _g(lambda: [int(x) for x in l.PlotColor]),
            _g(lambda: _r(l.PlotWeight)), _g(lambda: l.RenderMaterialIndex), _g(lambda: l.IgesLevel), _g(lambda: l.Expanded)]

def snapshot(m):
    """canonical, comparable description of a File3dm model (ids, geometry hashes, tables)"""
    objs = {}
    for i, o in enumerate(m.Objects):
        a = o.Attributes; g = o.Geometry
        objs[str(a.Id)] = {'type': str(g.ObjectType) if g is not None else None, 'geom': _fp(g) if g is not None else None,
                           'name': a.Name, 'layer': a.LayerIndex, 'color': [int(x) for x in a.ObjectColor], 'csrc': str(a.ColorSource),
                           'ustr': _us(a), 'gstr': _us(g) if g is not None else None, 'mat': a.MaterialIndex, 'x': _g(lambda: [a.LinetypeIndex, str(a.LinetypeSource), str(a.MaterialSource), [int(c) for c in a.PlotColor], str(a.PlotColorSource), _r(a.PlotWeight), str(a.PlotWeightSource), a.GroupCount, [int(i) for i in a.GetGroupList()] if a.GroupCount else [], a.DisplayOrder, a.CastsShadows, a.ReceivesShadows, a.WireDensity, a.Url, str(a.ObjectDecoration), str(a.ActiveSpace), str(a.ViewportId)]), 'visible': a.Visible, 'mode': str(a.Mode)}
    tab = lambda t, f: [f(x) for x in t]
    return {'version': m.ArchiveVersion, 'objects': objs, 'n_objects': len(m.Objects),
            'layers': tab(m.Layers, _layer),
            'materials': tab(m.Materials, lambda x: [str(x.Id), x.Name, [int(c) for c in x.DiffuseColor], x.Transparency]),
            'idefs': tab(m.InstanceDefinitions, lambda d: [str(d.Id), d.Name, sorted(str(i) for i in d.GetObjectIds()), _g(lambda: d.Description), _g(lambda: str(d.UpdateType)), _g(lambda: str(d.SourceArchive)), _us(d)]),
            'groups': len(m.Groups), 'views': [_view(v) for v in m.Views], 'named_views': [_view(v) for v in m.NamedViews], 'linetypes': len(m.Linetypes), 'bitmaps': len(m.Bitmaps),
            'extra': _extra(m),
            'embedded': _g(lambda: [len(m.EmbeddedFiles), sorted(str(p) for p in m.EmbeddedFilePaths()), [hashlib.sha1(str(m.GetEmbeddedFileAsBase64(p)).encode()).hexdigest()[:12] for p in sorted(str(p) for p in m.EmbeddedFilePaths())]]),
            'header': [_g(lambda k=k: str(getattr(m, k))) for k in ('ApplicationName', 'ApplicationUrl', 'ApplicationDetails', 'CreatedBy', 'LastEditedBy', 'Created', 'LastEdited')],
            'docstrings': _doc_strings(m),
            'units': str(m.Settings.ModelUnitSystem),
            'plugin': [_pd(p) for p in m.PlugInData],
            'rdk': hashlib.sha1(_canon_xml(str(m.RdkXml())).encode('utf-8', 'surrogatepass')).hexdigest()[:12]}

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

PREVIEW = 0x20008025   # properties-table record holding the thumbnail bitmap (the library rewrites it much smaller/blank)

def _find_record(b, table, code):
    """(table_off, rec_off, rec_len) of the single record `code` in top-level chunk `table`, else None"""
    import struct
    o = 32; hit = []
    while o + 12 <= len(b):
        t, l = struct.unpack_from('<Iq', b, o)
        if l < 0 or o + 12 + l > len(b): return None
        if t == table:
            r = o + 12
            while r + 12 <= o + 12 + l:
                t2, l2 = struct.unpack_from('<Iq', b, r)
                if t2 & 0x80000000: r += 12; continue
                if l2 < 0 or r + 12 + l2 > o + 12 + l: return None
                if t2 == code: hit.append((o, r, l2))
                r += 12 + l2
        if t == 0x7fff: break
        o += 12 + l
    return hit[0] if len(hit) == 1 else None

def restore_preview(src, tmp):
    """copy the source's preview-image record byte for byte into the output (record carries its own CRC; the table chunk has none).
    Returns True when restored or nothing to do, False when the layout is not understood (caller refuses)."""
    import struct
    a = open(src, 'rb').read(); b = bytearray(open(tmp, 'rb').read())
    ra, rb = _find_record(a, 0x10000014, PREVIEW), _find_record(bytes(b), 0x10000014, PREVIEW)
    if ra is None and rb is None: return True
    if ra is None or rb is None: return False
    pa = a[ra[1] + 12:ra[1] + 12 + ra[2]]
    if bytes(b[rb[1] + 12:rb[1] + 12 + rb[2]]) == pa: return True
    b[rb[1] + 12:rb[1] + 12 + rb[2]] = pa
    struct.pack_into('<q', b, rb[1] + 4, len(pa))
    tl = struct.unpack_from('<q', b, rb[0] + 4)[0]
    struct.pack_into('<q', b, rb[0] + 4, tl + len(pa) - rb[2])
    if len(b) < 20 or struct.unpack_from('<Iq', b, len(b) - 20)[:2] != (0x7fff, 8): return False   # end-of-file chunk stores the file length
    struct.pack_into('<q', b, len(b) - 8, len(b))
    with open(tmp, 'wb') as fh: fh.write(b)
    return True

def notes_of(path):
    """(is_html, text, visible, window ints) of the document notes record (0x20008022; rhino3dm exposes no Notes API so it was uncompared).
    The library bumps the record minor version, so the raw bytes differ; the content must not."""
    import struct
    b = open(path, 'rb').read(); r = _find_record(b, 0x10000014, 0x20008022)
    if r is None: return None
    p = b[r[1] + 12:r[1] + 12 + r[2]]
    try:
        html = p[4]; n = struct.unpack_from('<i', p, 5)[0]
        text = p[9:9 + 2 * n].decode('utf-16-le'); rest = p[9 + 2 * n:]
        return (html, text, struct.unpack_from('<i', rest, 0)[0], struct.unpack_from('<4i', rest, 4))
    except Exception: return 'unparsed'

def census(path):
    """count of (top-level table chunk, record typecode) in a 3dm file (archive >= V5 chunk framing, 8-byte lengths).
    Used as a second, byte-structure level check: a rewrite that drops table records must not be accepted."""
    import struct, collections
    b = open(path, 'rb').read(); c = collections.Counter()
    def walk(o, end, tag):
        while o + 12 <= end:
            t, l = struct.unpack_from('<Iq', b, o)
            if l < 0 or o + 12 + l > end: return o
            c[(tag, '%08x' % t)] += 1
            if tag == '': walk(o + 12, o + 12 + l, '%08x' % t)
            o += 12 + l
            if tag == '' and t == 0x7fff: return o   # end-of-file chunk
        return o
    stop = walk(32, len(b), '')
    if stop < len(b): c[('', 'trailing-bytes')] = len(b) - stop   # data after the last chunk; the library does not carry it over
    return c

def object_census(path):
    """Counter of the chunk typecodes found inside the object-table records (type, attributes, geometry, userdata, class-end ...).
    census() stops at the record level, so a rewrite that dropped a userdata/extra chunk inside an object record was invisible."""
    import struct, collections
    b = open(path, 'rb').read(); c = collections.Counter()
    def kids(o, end):
        while o + 12 <= end:
            t, l = struct.unpack_from('<Iq', b, o)
            if t & 0x80000000: yield t, o, 0; o += 12; continue
            if l < 0 or o + 12 + l > end: return
            yield t, o, l; o += 12 + l
    for t, o, l in kids(32, len(b)):
        if t == 0x10000013:
            for t2, o2, l2 in kids(o + 12, o + 12 + l):
                if t2 & 0x80000000: continue
                for t3, _, _ in kids(o2 + 12, o2 + 12 + l2): c[('obj', '%08x' % t3)] += 1
        if t == 0x7fff: break
    return c

# settings-table records whose payload bytes were identical after a no-edit rewrite in 100 percent of the 53 public V5+
# samples (document/render/analysis/etc settings); a difference after an edit that did not touch settings is refused.
STABLE_PAYLOAD = {('10000015', t) for t in ('20008035', '20008036', '20008039', '2000803a', '20008135', 'a0000038', 'a000003c')} | \
                 {('10000018', '20008073'), ('10000021', '20008076'), ('10000022', '20008077')}

def stable_payloads(path):
    """sha1 multiset of payloads for STABLE_PAYLOAD records"""
    import struct, collections
    b = open(path, 'rb').read(); c = collections.defaultdict(list); o = 32
    while o + 12 <= len(b):
        t, l = struct.unpack_from('<Iq', b, o)
        if l < 0 or o + 12 + l > len(b): break
        q = o + 12
        while q + 12 <= o + 12 + l:
            t2, l2 = struct.unpack_from('<Iq', b, q)
            if l2 < 0 or q + 12 + l2 > o + 12 + l: break
            k = ('%08x' % t, '%08x' % t2)
            if k in STABLE_PAYLOAD: c[k].append(hashlib.sha1(b[q + 12:q + 12 + l2]).hexdigest())
            q += 12 + l2
        o += 12 + l
    return {k: sorted(v) for k, v in c.items()}

# record typecodes the library legitimately swaps on rewrite (V6 archive settings/properties record variant)
CENSUS_SWAP = {'88200080', '99200080'}

def census_loss(a, b):
    """records present in the original census but fewer in the output"""
    return sorted('%s/%s: %d -> %d' % (k[0], k[1], n, b[k]) for k, n in a.items() if b[k] < n and k[1] not in CENSUS_SWAP)

def gate(m):
    """reasons the library cannot be trusted to round-trip this model; empty = ok"""
    why = []
    if any(o.Geometry is None for o in m.Objects): why.append('unreadable object(s) would be dropped')
    if m.ArchiveVersion not in (50, 60, 70, 80): why.append('archive version %s not writable' % m.ArchiveVersion)
    return why

LOCK_STALE_S = 600

def _lock(path):
    """exclusive lock file next to the target (portable, O_EXCL); a lock older than LOCK_STALE_S is treated as left by a killed save"""
    import time
    lk = path + '.3dmballet.lock'
    for _ in range(2):
        try:
            fd = os.open(lk, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600); os.write(fd, str(os.getpid()).encode()); os.close(fd); return lk
        except FileExistsError:
            try:
                if time.time() - os.stat(lk).st_mtime > LOCK_STALE_S: os.remove(lk); continue
            except OSError: pass
            raise Refused('another save of this file is in progress (lock %s)' % os.path.basename(lk))
        except OSError as e: raise Refused('cannot create lock file: %s' % e)
    raise Refused('cannot take lock')

def edit_file(path, edit, expect, backup=True, allow_settings=False):
    path = os.path.realpath(path)
    lk = _lock(path)
    try: return _edit_file(path, edit, expect, backup, allow_settings)
    finally:
        try: os.remove(lk)
        except OSError: pass

def _edit_file(path, edit, expect, backup=True, allow_settings=False):
    """edit(model) mutates the model; expect(diffs) -> True when the diffs are exactly the intended ones.
    Original is replaced only if every check passes. Returns list of diffs applied."""
    path = os.path.realpath(path)   # never replace a symlink itself; edit its target in place of the link
    import stat
    try: mode = os.stat(path).st_mode
    except OSError as e: raise Refused('cannot stat: %s' % e)
    if not stat.S_ISREG(mode): raise Refused('not a regular file')
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
    try: fd, tmp = tempfile.mkstemp(prefix='.3dmballet-', suffix='.tmp', dir=d); os.close(fd)
    except OSError as e: raise Refused('cannot create temp file next to source: %s' % e)
    try:
        if not _guarded_write(m, tmp, ver, WRITE_TIMEOUT): raise Refused('write failed')
        if ver >= 50 and not restore_preview(path, tmp): raise Refused('preview image record layout not understood')
        try: probe.probe(tmp)
        except probe.Unreadable as e: raise Refused('output ' + str(e))
        m2 = R.File3dm.Read(tmp)
        if m2 is None: raise Refused('output unreadable')
        after = snapshot(m2)
        if after['version'] != before['version']: raise Refused('archive version changed')
        if ver >= 50:
            lost = census_loss(census(path), census(tmp))
            lost = lost or ['object-record ' + x for x in census_loss(object_census(path), object_census(tmp))]
            if lost: raise Refused('output has fewer table records than the source: %s' % lost[:4])
            if not any(d.split()[0] in ('units', 'extra', 'header') for d in diff(before, after)) and not allow_settings:
                p0, p1 = stable_payloads(path), stable_payloads(tmp)
                bad = sorted('%s/%s' % k for k in p0 if p1.get(k) != p0[k])
                if bad: raise Refused('settings records changed by the save although no settings edit was requested: %s' % bad[:4])
        if ver >= 50 and notes_of(path) != notes_of(tmp): raise Refused('document notes changed by the save')
        c0 = _g(lambda: m.StartSectionComments, ''); c1 = _g(lambda: m2.StartSectionComments, '')
        if not c1.startswith(c0): raise Refused('file creation comments changed (the library may only append a line)')
        ds = diff(before, after)
        if not expect(ds): raise Refused('unexpected differences: %s' % ds[:5])
        st1 = os.stat(path)
        if (st1.st_size, st1.st_mtime_ns, hashlib.sha256(open(path, 'rb').read()).hexdigest()) != sig0:
            raise Refused('source changed during edit; refusing to overwrite')
        try:
            shutil.copymode(path, tmp)   # mkstemp creates 0600; keep the original permissions
            with open(tmp, 'r+b') as fh: os.fsync(fh.fileno())
        except OSError as e: raise Refused('cannot finalise output, original untouched: %s' % e)
        if backup:
            try:
                bak = path + '.bak'; k = 0
                while os.path.lexists(bak): k += 1; bak = '%s.bak.%d' % (path, k)   # never overwrite an earlier backup
                shutil.copy2(path, bak)
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
