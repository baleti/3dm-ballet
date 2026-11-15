import os, pytest
import rhino3dm as R
from tm3dballet import write

def _make(path, idx):
    m = R.File3dm(); l = R.Layer(); l.Name = 'L0'; m.Layers.Add(l)
    a = R.ObjectAttributes(); a.LayerIndex = idx
    m.Objects.AddPoint(R.Point3d(1, 2, 3), a); m.Objects.AddPoint(R.Point3d(4, 5, 6))
    assert m.Write(path, 7)

@pytest.mark.parametrize('idx', [5, -1, 2147483647, -2147483648])
def test_object_with_dangling_layer_index(idx, tmp_path):
    p = str(tmp_path / 'a.3dm'); _make(p, idx); orig = open(p, 'rb').read()
    before = [o.Attributes.LayerIndex for o in R.File3dm.Read(p).Objects]
    try: write.rename_layer(p, 'L0', 'Renamed')
    except write.Refused: assert open(p, 'rb').read() == orig and os.listdir(tmp_path) == ['a.3dm']; return
    m = R.File3dm.Read(p)
    assert [o.Attributes.LayerIndex for o in m.Objects] == before     # object-layer links not silently repaired
    assert m.Layers[0].Name == 'Renamed' and open(p + '.bak', 'rb').read() == orig
