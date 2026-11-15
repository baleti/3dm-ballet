import os, shutil, signal, subprocess, sys, textwrap, time, pytest
import rhino3dm as R
from tm3dballet import write
D = os.path.join(os.path.dirname(__file__), 'data')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(D, 'V7-v7_my_brep.3dm')

@pytest.mark.skipif(os.name != 'posix', reason='signals')
def test_stopped_and_continued_save_completes_valid(tmp_path):
    p = str(tmp_path / 'a.3dm'); shutil.copy(SRC, p); orig = open(p, 'rb').read()
    code = 'import sys\nfrom tm3dballet import write\nwrite.rename_layer(sys.argv[1], "brep", "Renamed")\nprint("OK")'
    pr = subprocess.Popen([sys.executable, '-c', code, p], cwd=ROOT, stdout=subprocess.PIPE, text=True,
                          env=dict(os.environ, PYTHONPATH=os.path.join(ROOT, '.deps') + ':' + ROOT))
    for i in range(6):
        time.sleep(0.15); pr.send_signal(signal.SIGSTOP)
        assert open(p, 'rb').read() in (orig, open(p, 'rb').read())     # readable while stopped
        time.sleep(0.2); pr.send_signal(signal.SIGCONT)
    assert pr.communicate(timeout=120)[0].strip() == 'OK'
    assert R.File3dm.Read(p).Layers[0].Name == 'Renamed' and open(p + '.bak', 'rb').read() == orig
    assert sorted(os.listdir(tmp_path)) == ['a.3dm', 'a.3dm.bak']

@pytest.mark.parametrize('name', ['A.3dm', 'sp ace.3dm', "q'uote\".3dm", 'new\nline.3dm', 'x' * 245 + '.3dm', 'ünï.3dm'])
def test_odd_file_names_save_or_refuse_cleanly(name, tmp_path):
    p = str(tmp_path / name)
    try: shutil.copy(SRC, p)
    except OSError: pytest.skip('fs rejects name')
    orig = open(p, 'rb').read()
    try: write.rename_layer(p, 'brep', 'Renamed')
    except write.Refused: assert open(p, 'rb').read() == orig; return
    assert R.File3dm.Read(p).Layers[0].Name == 'Renamed'
    left = [f for f in os.listdir(tmp_path) if f != name]
    assert len(left) == 1 and left[0].startswith(name[:100]) and open(os.path.join(tmp_path, left[0]), 'rb').read() == orig, left

def test_case_twin_in_same_dir_keeps_both_backups_separate(tmp_path):
    a = str(tmp_path / 'a.3dm'); b = str(tmp_path / 'A.3dm'); shutil.copy(SRC, a); shutil.copy(SRC, b)
    if len(os.listdir(tmp_path)) < 2: pytest.skip('case-insensitive fs')
    write.rename_layer(a, 'brep', 'One'); write.rename_layer(b, 'brep', 'Two')
    assert R.File3dm.Read(a).Layers[0].Name == 'One' and R.File3dm.Read(b).Layers[0].Name == 'Two'
    assert open(a + '.bak', 'rb').read() == open(b + '.bak', 'rb').read() == open(SRC, 'rb').read()

@pytest.mark.skipif(not os.path.isdir('/dev/shm'), reason='no /dev/shm')
def test_tmpdir_on_other_filesystem_is_irrelevant(tmp_path, monkeypatch):
    """Temp file must live beside the target (same fs, atomic rename), whatever TMPDIR says."""
    import tempfile
    other = tempfile.mkdtemp(dir='/dev/shm'); monkeypatch.setenv('TMPDIR', other); monkeypatch.setattr(tempfile, 'tempdir', None)
    try:
        d = tmp_path / 'proj'; d.mkdir(); p = str(d / 'a.3dm'); shutil.copy(SRC, p)
        write.rename_layer(p, 'brep', 'Renamed')
        assert R.File3dm.Read(p).Layers[0].Name == 'Renamed' and os.listdir(other) == []
        assert sorted(os.listdir(d)) == ['a.3dm', 'a.3dm.bak']
    finally: shutil.rmtree(other, ignore_errors=True)
