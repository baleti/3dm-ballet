import os, shutil, pytest
import rhino3dm as R
from tm3dballet import write
SRC = os.path.join(os.path.dirname(__file__), 'data', 'V7-v7_my_brep.3dm')

@pytest.mark.parametrize('new', ['Default', 'default', 'DEFAULT', 'Layer 01', 'Layer 00'])
def test_rename_to_library_default_names(new, tmp_path):
    p = str(tmp_path / 'a.3dm'); shutil.copy(SRC, p); orig = open(p, 'rb').read()
    ids = [str(l.Id) for l in R.File3dm.Read(p).Layers]
    try: write.rename_layer(p, 'brep', new)
    except write.Refused: assert open(p, 'rb').read() == orig and os.listdir(tmp_path) == ['a.3dm']; return
    m = R.File3dm.Read(p)
    assert [l.Name for l in m.Layers] == [new] and [str(l.Id) for l in m.Layers] == ids   # no extra layer, same id
    assert open(p + '.bak', 'rb').read() == orig
