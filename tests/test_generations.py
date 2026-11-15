import os, glob, shutil, pytest
import rhino3dm as R
from tm3dballet import write
D = os.path.dirname(__file__)
FILES = sorted(glob.glob(os.path.join(D, 'data', 'V[67]*.3dm')) + glob.glob(os.path.join(D, 'data_ext', '*.3dm')))

@pytest.mark.parametrize('src', FILES, ids=os.path.basename)
def test_ten_generations_no_drift(src, tmp_path):
    p = str(tmp_path / 'a.3dm'); shutil.copy(src, p)
    m = R.File3dm.Read(p)
    if m is None or len(m.Layers) == 0: pytest.skip('no layers')
    old = m.Layers[0].Name; snaps = []
    try: write.rename_layer(p, old, 'G0')
    except write.Refused: pytest.skip('refused (not saveable by design)')
    base = os.path.getsize(p); name = 'G0'
    for i in range(1, 10):
        write.rename_layer(p, name, 'G%d' % i); name = 'G%d' % i
        assert write.structure_problem(p) is None
        assert abs(os.path.getsize(p) - base) <= 64, 'size drift %d -> %d' % (base, os.path.getsize(p))
    write.rename_layer(p, name, old)
    a = write.snapshot(R.File3dm.Read(src)); b = write.snapshot(R.File3dm.Read(p))
    assert write.diff(a, b) == [] or all('creat' in str(x).lower() or 'comment' in str(x).lower() for x in write.diff(a, b)), write.diff(a, b)[:3]
    baks = [n for n in os.listdir(tmp_path) if '.bak' in n]
    assert len(baks) == 11 and open(str(tmp_path / 'a.3dm.bak'), 'rb').read() == open(src, 'rb').read()
