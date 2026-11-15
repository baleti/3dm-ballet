import os, shutil, pytest
import rhino3dm as R
from tm3dballet import write
SRC = os.path.join(os.path.dirname(__file__), 'data', 'V7-v7_my_brep.3dm')

def _setup(tmp_path, suffix):
    d = tmp_path / 'd'; d.mkdir(); v = tmp_path / 'victim'; v.write_bytes(b'VICTIM DATA')
    p = str(d / 'a.3dm'); shutil.copy(SRC, p); os.symlink(str(v), p + suffix)
    return p, v

@pytest.mark.parametrize('suffix', ['.bak', '.3dmballet.lock'])
def test_preplaced_symlink_never_written_through(suffix, tmp_path):
    p, v = _setup(tmp_path, suffix); orig = open(p, 'rb').read()
    try: write.rename_layer(p, 'brep', 'Renamed')
    except write.Refused: assert open(p, 'rb').read() == orig
    else:
        assert R.File3dm.Read(p).Layers[0].Name == 'Renamed'
        baks = [n for n in os.listdir(os.path.dirname(p)) if '.bak' in n and not os.path.islink(os.path.join(os.path.dirname(p), n))]
        assert baks and all(open(os.path.join(os.path.dirname(p), n), 'rb').read() == orig for n in baks)
    assert v.read_bytes() == b'VICTIM DATA'

def test_dangling_symlink_bak(tmp_path):
    d = tmp_path / 'd'; d.mkdir(); p = str(d / 'a.3dm'); shutil.copy(SRC, p); gone = tmp_path / 'gone'
    os.symlink(str(gone), p + '.bak'); orig = open(p, 'rb').read()
    try: write.rename_layer(p, 'brep', 'Renamed')
    except write.Refused: assert open(p, 'rb').read() == orig
    assert not gone.exists()

def test_source_itself_symlink_to_file_elsewhere(tmp_path):
    real = tmp_path / 'real'; real.mkdir(); d = tmp_path / 'd'; d.mkdir()
    r = str(real / 'm.3dm'); shutil.copy(SRC, r); l = str(d / 'link.3dm'); os.symlink(r, l); orig = open(SRC, 'rb').read()
    try: write.rename_layer(l, 'brep', 'Renamed')
    except write.Refused: assert open(r, 'rb').read() == orig and os.path.islink(l); return
    assert os.path.islink(l) and R.File3dm.Read(r).Layers[0].Name == 'Renamed'      # link kept, target updated
    assert any(open(str(real / n), 'rb').read() == orig for n in os.listdir(real) if '.bak' in n)
