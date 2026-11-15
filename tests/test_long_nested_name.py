import os, pytest
import rhino3dm as R
from tm3dballet import write

def _make(path):
    m = R.File3dm(); p = R.Layer(); p.Name = 'parent'; m.Layers.Add(p)
    c = R.Layer(); c.Name = 'child'; c.ParentLayerId = m.Layers[0].Id; m.Layers.Add(c)
    m.Objects.AddPoint(R.Point3d(1, 2, 3)); assert m.Write(path, 7)

@pytest.mark.parametrize('n', [255, 256, 1000, 4096, 70000])
@pytest.mark.parametrize('which', ['parent', 'child'])
def test_long_name_on_nested(n, which, tmp_path):
    p = str(tmp_path / 'a.3dm'); _make(p); orig = open(p, 'rb').read(); new = 'N' * (n - 1) + 'é'
    ids = [(str(l.Id), str(l.ParentLayerId)) for l in R.File3dm.Read(p).Layers]
    try: write.rename_layer(p, which, new)
    except write.Refused: assert open(p, 'rb').read() == orig and os.listdir(tmp_path) == ['a.3dm']; return
    m = R.File3dm.Read(p); names = [l.Name for l in m.Layers]
    assert names == ([new, 'child'] if which == 'parent' else ['parent', new])
    assert [(str(l.Id), str(l.ParentLayerId)) for l in m.Layers] == ids and write.structure_problem(p) is None
    assert open(p + '.bak', 'rb').read() == orig
