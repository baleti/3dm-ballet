import os, shutil, pytest
import rhino3dm as R
from tm3dballet import write
SRC = os.path.join(os.path.dirname(__file__), 'data', 'V7-v7_my_brep.3dm')

@pytest.mark.parametrize('new', ['12345678-1234-1234-1234-123456789abc', '0', '-1', '::lead', 'trail::', '<b>x</b>', '../../etc', 'a/b', 'a\\b', '%s%d', '{0}', "'; DROP", 'NUL', 'Ünï::x'])
def test_odd_names_exact_or_refused(new, tmp_path):
    p = str(tmp_path / 'a.3dm'); shutil.copy(SRC, p); orig = open(p, 'rb').read()
    try: write.rename_layer(p, 'brep', new)
    except write.Refused: assert open(p, 'rb').read() == orig; return
    ls = R.File3dm.Read(p).Layers
    assert [l.Name for l in ls] == [new] and len(ls) == 1
    assert sorted(os.listdir(tmp_path)) == ['a.3dm', 'a.3dm.bak'] and open(p + '.bak', 'rb').read() == orig

@pytest.mark.skipif(os.name != 'posix', reason='symlinks')
def test_source_dir_is_symlink_artifacts_in_real_dir(tmp_path):
    real = tmp_path / 'real'; real.mkdir(); link = tmp_path / 'link'; os.symlink(real, link)
    shutil.copy(SRC, real / 'a.3dm'); orig = open(real / 'a.3dm', 'rb').read()
    write.rename_layer(str(link / 'a.3dm'), 'brep', 'Renamed')
    assert sorted(os.listdir(real)) == ['a.3dm', 'a.3dm.bak'] and open(real / 'a.3dm.bak', 'rb').read() == orig
    assert os.path.islink(link) and R.File3dm.Read(str(real / 'a.3dm')).Layers[0].Name == 'Renamed'
