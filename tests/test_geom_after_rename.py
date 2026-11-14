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
