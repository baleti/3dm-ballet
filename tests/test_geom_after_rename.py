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
