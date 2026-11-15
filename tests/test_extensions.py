import os, shutil, subprocess, sys, pytest
import rhino3dm as R
from tm3dballet import write
SRC = os.path.join(os.path.dirname(__file__), 'data', 'V7-v7_my_brep.3dm')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

@pytest.mark.parametrize('name', ['a.3DM', 'noext', 'a.3dm.txt', '.3dm', 'a.'])
def test_save_independent_of_extension(name, tmp_path):
    p = str(tmp_path / name); shutil.copy(SRC, p); orig = open(p, 'rb').read()
    write.rename_layer(p, 'brep', 'Renamed')
    assert R.File3dm.Read(p).Layers[0].Name == 'Renamed' and open(p + '.bak', 'rb').read() == orig
    assert len(os.listdir(tmp_path)) == 2

@pytest.mark.parametrize('name', ['a.3DM', 'noext', 'a.3dm.txt'])
def test_cli_info_and_dry_run_no_traceback(name, tmp_path):
    p = str(tmp_path / name); shutil.copy(SRC, p); orig = open(p, 'rb').read()
    env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, '.deps') + os.pathsep + ROOT)
    for args in (['info', p], ['rename-layer', p, 'brep', 'X']):
        r = subprocess.run([sys.executable, '-m', 'tm3dballet.cli'] + args, capture_output=True, text=True, cwd=ROOT, env=env, timeout=120)
        assert 'Traceback' not in r.stderr and r.returncode in (0, 1, 2), (args, r.stdout, r.stderr)
    assert open(p, 'rb').read() == orig and os.listdir(tmp_path) == [name]
