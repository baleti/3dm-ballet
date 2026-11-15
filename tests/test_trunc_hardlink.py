import glob, os, shutil, pytest
import rhino3dm as R
from tm3dballet import write
D = os.path.join(os.path.dirname(__file__), 'data')
FILES = sorted(glob.glob(os.path.join(D, '*.3dm')))[::6]   # spread of versions, keeps run short

@pytest.mark.parametrize('f', FILES, ids=os.path.basename)
@pytest.mark.parametrize('pct', [50, 90, 99])
def test_truncated_source_refused_untouched(f, pct, tmp_path):
    b = open(f, 'rb').read(); p = str(tmp_path / 'a.3dm')
    open(p, 'wb').write(b[:len(b) * pct // 100]); before = open(p, 'rb').read()
    try: lay = R.File3dm.Read(p).Layers[0].Name
    except Exception: lay = 'x'
    try: write.rename_layer(p, lay, 'Zed')
    except write.Refused: pass
    assert open(p, 'rb').read() == before and sorted(os.listdir(tmp_path)) == ['a.3dm']

@pytest.mark.skipif(os.name != 'posix', reason='hardlinks')
def test_hardlink_twin_not_corrupted(tmp_path):
    p = str(tmp_path / 'a.3dm'); t = str(tmp_path / 'twin.3dm')
    shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), p); os.link(p, t); orig = open(p, 'rb').read()
    with pytest.raises(write.Refused): write.rename_layer(p, 'brep', 'Renamed')   # by design: refuse rather than detach the twin
    assert open(p, 'rb').read() == orig and open(t, 'rb').read() == orig and sorted(os.listdir(tmp_path)) == ['a.3dm', 'twin.3dm']
