import glob, os, shutil, pytest
import rhino3dm as R
from tm3dballet import write
D = os.path.join(os.path.dirname(__file__), 'data')
FILES = sorted(glob.glob(os.path.join(D, '*.3dm')))

@pytest.mark.parametrize('f', FILES, ids=os.path.basename)
def test_rename_size_bounded_and_repeat_stable(f, tmp_path):
    p = str(tmp_path / 'a.3dm'); shutil.copy(f, p); n0 = os.path.getsize(p)
    try: lay = R.File3dm.Read(p).Layers[0].Name
    except Exception: pytest.skip('unreadable')
    try: write.rename_layer(p, lay, 'Zq1')
    except write.Refused: pytest.skip('refused by design')
    n1 = os.path.getsize(p)
    assert 0.5 * n0 < n1 < 2 * n0 + 4096, (n0, n1)
    write.rename_layer(p, 'Zq1', 'Zq2'); write.rename_layer(p, 'Zq2', 'Zq1')
    assert os.path.getsize(p) == n1                      # same state, same size: no drift or growth
    assert R.File3dm.Read(p).Layers[0].Name == 'Zq1'
    assert len([x for x in os.listdir(tmp_path) if x.startswith('a.3dm.bak')]) == 3
