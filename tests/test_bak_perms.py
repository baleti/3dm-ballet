import os, shutil, pytest
import rhino3dm as R
from tm3dballet import write
SRC = os.path.join(os.path.dirname(__file__), 'data', 'V7-v7_my_brep.3dm')

@pytest.mark.skipif(os.name != 'posix', reason='modes')
@pytest.mark.parametrize('kind', ['ro_file', 'dir'])
def test_existing_bak_readonly_or_dir(kind, tmp_path):
    p = str(tmp_path / 'a.3dm'); shutil.copy(SRC, p); orig = open(p, 'rb').read(); b = p + '.bak'
    if kind == 'dir': os.mkdir(b); open(os.path.join(b, 'keep'), 'w').write('x')
    else: open(b, 'wb').write(b'precious'); os.chmod(b, 0o444)
    try: write.rename_layer(p, 'brep', 'Renamed')
    except write.Refused: assert open(p, 'rb').read() == orig; return
    assert R.File3dm.Read(p).Layers[0].Name == 'Renamed'
    if kind == 'dir': assert open(os.path.join(b, 'keep')).read() == 'x'
    else: assert open(b, 'rb').read() == b'precious'
    baks = [f for f in os.listdir(tmp_path) if f.startswith('a.3dm.bak.')]
    assert len(baks) == 1 and open(os.path.join(tmp_path, baks[0]), 'rb').read() == orig

@pytest.mark.skipif(os.name != 'posix' or os.geteuid() == 0, reason='modes')
def test_readonly_source_file(tmp_path):
    p = str(tmp_path / 'a.3dm'); shutil.copy(SRC, p); os.chmod(p, 0o444); orig = open(p, 'rb').read()
    try: write.rename_layer(p, 'brep', 'Renamed')
    except write.Refused: assert open(p, 'rb').read() == orig; assert sorted(os.listdir(tmp_path)) == ['a.3dm']; return
    assert os.stat(p).st_mode & 0o777 == 0o444 and open(p + '.bak', 'rb').read() == orig   # saved: mode kept, backup exact

@pytest.mark.skipif(os.name != 'posix', reason='modes')
@pytest.mark.parametrize('mode', [0o600, 0o640, 0o664, 0o755])
def test_mode_preserved_on_file_and_backup_readable(mode, tmp_path):
    p = str(tmp_path / 'a.3dm'); shutil.copy(SRC, p); os.chmod(p, mode); orig = open(p, 'rb').read()
    write.rename_layer(p, 'brep', 'Renamed')
    assert os.stat(p).st_mode & 0o777 == mode and open(p + '.bak', 'rb').read() == orig
    assert os.stat(p + '.bak').st_mode & 0o777 == mode      # backup carries the source mode, never more open
