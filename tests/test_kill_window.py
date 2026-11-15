import os, shutil, subprocess, sys, pytest
import rhino3dm as R
from tm3dballet import write
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'tests', 'data', 'V7-v7_my_brep.3dm')
CODE = """
import os, sys
from tm3dballet import write
mode, p = sys.argv[1], sys.argv[2]
if mode == 'before_replace':
    def r(a, b): os._exit(9)
    os.replace = r
elif mode == 'after_replace':
    real = os.replace
    def r(a, b): real(a, b); os._exit(9)
    os.replace = r
elif mode == 'at_fsync_dir':
    write.fsync_dir = lambda d: os._exit(9)
write.rename_layer(p, 'brep', 'Renamed')
"""
def _kill(mode, p):
    env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, '.deps') + os.pathsep + ROOT)
    return subprocess.run([sys.executable, '-c', CODE, mode, p], env=env, cwd=ROOT, capture_output=True, timeout=300).returncode

@pytest.mark.parametrize('mode', ['before_replace', 'after_replace', 'at_fsync_dir'])
def test_process_death_in_commit_window(mode, tmp_path):
    p = str(tmp_path / 'a.3dm'); shutil.copy(SRC, p); orig = open(SRC, 'rb').read()
    assert _kill(mode, p) == 9
    cur = open(p, 'rb').read()
    f = R.File3dm.Read(p); assert f is not None and len(f.Layers) == 1
    if mode == 'before_replace': assert cur == orig and f.Layers[0].Name == 'brep'
    else: assert f.Layers[0].Name == 'Renamed' and write.structure_problem(p) is None
    bak = [n for n in os.listdir(tmp_path) if n.startswith('a.3dm.bak')]
    assert bak and all(open(str(tmp_path / n), 'rb').read() == orig for n in bak)   # backup exact whenever it exists
    # leftovers (tmp, lock) must not block a later save
    write.rename_layer(p, 'Renamed' if mode != 'before_replace' else 'brep', 'Second')
    assert R.File3dm.Read(p).Layers[0].Name == 'Second'
    write.restore_backup(p); assert R.File3dm.Read(p).Layers[0].Name in ('brep', 'Renamed')
