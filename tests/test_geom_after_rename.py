"""Item 128: object geometry (bbox, point counts) identical before and after a layer rename, independent of glb/snapshot."""
import glob, os, shutil, pytest
import rhino3dm as R
from tm3dballet import write
D = os.path.join(os.path.dirname(__file__), 'data')
FILES = sorted(glob.glob(os.path.join(D, '*.3dm')) + glob.glob(os.path.join(D, '..', 'data_ext', '*.3dm')))

def desc(o):
    g = o.Geometry
    if g is None: return ('none',)
    t = str(g.ObjectType)
    try:
        b = g.GetBoundingBox(); bb = tuple(round(v, 9) for v in (b.Min.X, b.Min.Y, b.Min.Z, b.Max.X, b.Max.Y, b.Max.Z))
    except Exception: bb = None
    n = None
    for a in ('Vertices', 'Points'):
        try: n = len(getattr(g, a)); break
        except Exception: pass
    for a in ('Faces', 'Edges'):
        try: n = (n, len(getattr(g, a)))
        except Exception: pass
    return (str(o.Attributes.Id), t, bb, n)

@pytest.mark.parametrize('f', FILES, ids=os.path.basename)
def test_geometry_unchanged_by_rename(f, tmp_path):
    m = R.File3dm.Read(f)
    if write.gate(m) or not len(m.Layers): pytest.skip('refused')
    before = [desc(o) for o in m.Objects]; old = m.Layers[0].Name
    p = str(tmp_path / 'a.3dm'); shutil.copy(f, p)
    try: write.rename_layer(p, old, old + '_x')
    except write.Refused: pytest.skip('refused')
    after = [desc(o) for o in R.File3dm.Read(p).Objects]
    assert sorted(map(repr, before)) == sorted(map(repr, after))


def lay_fields(l):
    c, p = l.Color, l.PlotColor
    return (str(l.Id), str(l.ParentLayerId), l.Visible, l.Locked, l.Index, (c[0], c[1], c[2], c[3]), (p[0], p[1], p[2], p[3]),
            l.LinetypeIndex, l.PlotWeight, l.RenderMaterialIndex, l.ExpandedInLayerUI if hasattr(l, 'ExpandedInLayerUI') else None)

@pytest.mark.parametrize('f', FILES, ids=os.path.basename)
def test_layer_fields_and_object_layer_index_unchanged_by_rename(f, tmp_path):
    """items 147, 149, 150: id, parent, visible, locked, colours, linetype, plot weight, material of every layer except the name; objects keep their layer index"""
    m = R.File3dm.Read(f)
    if write.gate(m) or not len(m.Layers): pytest.skip('refused')
    b = [lay_fields(l) for l in m.Layers]; ob = [o.Attributes.LayerIndex for o in m.Objects]; old = m.Layers[0].Name
    p = str(tmp_path / 'a.3dm'); shutil.copy(f, p)
    try: write.rename_layer(p, old, old + '_x')
    except write.Refused: pytest.skip('refused')
    m2 = R.File3dm.Read(p)
    assert [lay_fields(l) for l in m2.Layers] == b
    assert [o.Attributes.LayerIndex for o in m2.Objects] == ob


def test_parent_rename_children_untouched_and_paths_follow(tmp_path):
    """item 146: renaming a parent keeps the child records (parent id link) identical; only the parent's name and the children's full paths change"""
    import uuid
    from tm3dballet import reader
    m = R.File3dm(); ids = {}
    for n, par in [('Top', None), ('Mid', 'Top'), ('Leaf', 'Mid'), ('Other', None)]:
        l = R.Layer(); l.Name = n; l.Id = uuid.uuid4()
        if par: l.ParentLayerId = ids[par]
        m.Layers.Add(l); ids[n] = l.Id
    a = R.ObjectAttributes(); a.LayerIndex = 2; m.Objects.AddPoint(R.Point3d(1, 2, 3), a)
    f = str(tmp_path / 'a.3dm'); assert m.Write(f, 7)
    r0 = {l.Name: l.Encode() for l in R.File3dm.Read(f).Layers}
    write.rename_layer(f, 'Top', 'Roof')
    m2 = R.File3dm.Read(f); r1 = {l.Name: l.Encode() for l in m2.Layers}
    assert sorted(r1) == ['Leaf', 'Mid', 'Other', 'Roof']
    for n in ('Mid', 'Leaf', 'Other'): assert r1[n] == r0[n], n
    paths = sorted(p['path'] for p in reader._layer_paths(m2))
    assert paths == ['Other', 'Roof', 'Roof::Mid', 'Roof::Mid::Leaf']
    assert m2.Objects[0].Attributes.LayerIndex == 2
    write.rename_layer(f, 'Roof::Mid::Leaf', 'Tip'); assert 'Roof::Mid::Tip' in [p['path'] for p in reader._layer_paths(R.File3dm.Read(f))]


def test_layer_user_strings_and_material_survive_rename(tmp_path):
    """item 148: per-layer user strings (unicode too) and render material index survive a rename of that layer and of a sibling"""
    m = R.File3dm(); mat = R.Material(); mat.Name = 'Red'; m.Materials.Add(mat)
    for n in ('A', 'B'):
        l = R.Layer(); l.Name = n; l.RenderMaterialIndex = 0
        l.SetUserString('k_' + n, 'vé中_' + n); l.SetUserString('shared', 'x' * 500); m.Layers.Add(l)
    f = str(tmp_path / 'a.3dm'); assert m.Write(f, 7)
    def snap(p):
        mm = R.File3dm.Read(p); return [(l.Name, l.RenderMaterialIndex, sorted(l.GetUserStrings())) for l in mm.Layers], len(mm.Materials)
    s0 = snap(f); assert s0[0][0][2], 'fixture has no user strings'
    write.rename_layer(f, 'A', 'A2'); s1 = snap(f)
    assert s1[0][0][0] == 'A2' and s1[0][0][1:] == s0[0][0][1:] and s1[0][1] == s0[0][1] and s1[1] == s0[1]
    write.rename_layer(f, 'B', 'B2'); s2 = snap(f)
    assert [x[1:] for x in s2[0]] == [x[1:] for x in s0[0]] and s2[1] == s0[1]


def test_many_objects_identical_after_rename(tmp_path):
    """item 151: 3000 points and lines: per-object fingerprints (type, bbox, counts, name) unchanged by a rename. (152: rhino3dm cannot author
    embedded bitmaps; real bitmap/render tables are covered byte-for-byte by the table sweeps on the public samples.)"""
    m = R.File3dm(); L = R.Layer(); L.Name = 'A'; m.Layers.Add(L)
    for i in range(3000):
        a = R.ObjectAttributes(); a.LayerIndex = 0; a.Name = 'o%d' % i
        if i % 2: m.Objects.AddPoint(R.Point3d(i, i * .5, -i), a)
        else: m.Objects.AddLine(R.Point3d(i, 0, 0), R.Point3d(i, 1, 2), a)
    f = str(tmp_path / 'a.3dm'); assert m.Write(f, 7)
    key = lambda mm: sorted(map(repr, (desc(o) + (o.Attributes.Name,) for o in mm.Objects)))
    d0 = key(R.File3dm.Read(f)); write.rename_layer(f, 'A', 'B')
    m1 = R.File3dm.Read(f)
    assert len(m1.Objects) == 3000 and key(m1) == d0 and [l.Name for l in m1.Layers] == ['B']
