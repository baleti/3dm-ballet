import os, shutil, pytest
import rhino3dm as R
from tm3dballet import write
SRC = os.path.join(os.path.dirname(__file__), 'data', 'V7-v7_my_brep.3dm')

@pytest.mark.parametrize('name', ['a.3dm.bak', 'a.3dm.bak.1', 'a.3dm.lock', '.3dmballet-x.tmp', 'a.3dm.tmp', 'x.3dm.bak.bak'])
def test_source_named_like_an_artifact(name, tmp_path):
    p = str(tmp_path / name); shutil.copy(SRC, p); orig = open(SRC, 'rb').read()
    try: write.rename_layer(p, 'brep', 'Renamed')
    except write.Refused: assert open(p, 'rb').read() == orig and os.listdir(tmp_path) == [name]; return
    assert R.File3dm.Read(p).Layers[0].Name == 'Renamed'
    others = [n for n in os.listdir(tmp_path) if n != name]
    assert len(others) == 1 and open(str(tmp_path / others[0]), 'rb').read() == orig   # exactly one exact backup, nothing else
    write.restore_backup(p); assert R.File3dm.Read(p).Layers[0].Name == 'brep'

def test_two_sources_share_backup_namespace(tmp_path):
    # a.3dm and a.3dm.bak both real models: saving a.3dm must not overwrite the other model
    a = str(tmp_path / 'a.3dm'); b = a + '.bak'; shutil.copy(SRC, a); shutil.copy(SRC, b)
    R_b = open(b, 'rb').read(); write.rename_layer(b, 'brep', 'B')   # b saved first, makes b.bak
    write.rename_layer(a, 'brep', 'A')
    assert R.File3dm.Read(a).Layers[0].Name == 'A' and R.File3dm.Read(b).Layers[0].Name == 'B'
    baks = [n for n in os.listdir(tmp_path) if '.bak' in n and n != 'a.3dm.bak']
    assert all(open(str(tmp_path / n), 'rb').read() == R_b for n in baks) and len(baks) == 2
