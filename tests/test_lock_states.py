import os, shutil, subprocess, sys, pytest
import rhino3dm as R
from tm3dballet import write
SRC = os.path.join(os.path.dirname(__file__), 'data', 'V7-v7_my_brep.3dm')
pytestmark = pytest.mark.skipif(os.name != 'posix', reason='pids')

def mk(tmp_path):
    p = str(tmp_path / 'a.3dm'); shutil.copy(SRC, p); return p, open(p, 'rb').read()

def dead_pid():
    pr = subprocess.Popen([sys.executable, '-c', 'pass']); pr.wait(); return pr.pid

def test_fresh_lock_of_live_other_process_blocks(tmp_path):
    p, orig = mk(tmp_path); sl = subprocess.Popen(['sleep', '30'])
    try:
        open(p + '.3dmballet.lock', 'w').write(str(sl.pid))
        with pytest.raises(write.Refused, match='in progress'): write.rename_layer(p, 'brep', 'R')
        assert open(p, 'rb').read() == orig and os.path.exists(p + '.3dmballet.lock')    # foreign lock not removed
    finally: sl.kill(); sl.wait()

def test_fresh_lock_of_dead_pid_is_broken(tmp_path):
    p, orig = mk(tmp_path); open(p + '.3dmballet.lock', 'w').write(str(dead_pid()))
    write.rename_layer(p, 'brep', 'R')
    assert R.File3dm.Read(p).Layers[0].Name == 'R' and not os.path.exists(p + '.3dmballet.lock')

@pytest.mark.parametrize('content', [b'', b'garbage', b'-1', b'0', b'\xff\xfe', b'9' * 40])
def test_fresh_garbage_lock_is_respected_not_crashing(content, tmp_path):
    p, orig = mk(tmp_path); open(p + '.3dmballet.lock', 'wb').write(content)
    with pytest.raises(write.Refused): write.rename_layer(p, 'brep', 'R')
    assert open(p, 'rb').read() == orig and sorted(os.listdir(tmp_path)) == ['a.3dm', 'a.3dm.3dmballet.lock']

def test_lock_is_a_directory_refused_cleanly(tmp_path):
    p, orig = mk(tmp_path); os.mkdir(p + '.3dmballet.lock')
    with pytest.raises(write.Refused): write.rename_layer(p, 'brep', 'R')
    assert open(p, 'rb').read() == orig and os.path.isdir(p + '.3dmballet.lock')
