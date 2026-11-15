import os, shutil, time, pytest
from tm3dballet import write
SRC = os.path.join(os.path.dirname(__file__), 'data', 'V7-v7_my_brep.3dm')

def _run(tmp_path, mutate, monkeypatch):
    p = str(tmp_path / 'a.3dm'); shutil.copy(SRC, p)
    real = write.diff
    def hooked(a, b):
        monkeypatch.setattr(write, 'diff', real); mutate(p); return real(a, b)
    monkeypatch.setattr(write, 'diff', hooked)
    with pytest.raises(write.Refused, match='source changed|changed by the save|not readable|damaged|layer record'):
        write.rename_layer(p, 'brep', 'Renamed')
    return p

def test_other_writer_appends(tmp_path, monkeypatch):
    def mut(p): open(p, 'ab').write(b'x')
    p = _run(tmp_path, mut, monkeypatch)
    assert open(p, 'rb').read() == open(SRC, 'rb').read() + b'x'
    assert os.listdir(tmp_path) == ['a.3dm']

def test_other_writer_same_size_same_mtime(tmp_path, monkeypatch):
    def mut(p):
        st = os.stat(p); b = bytearray(open(p, 'rb').read()); b[-20] ^= 1
        open(p, 'wb').write(bytes(b)); os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))
    p = _run(tmp_path, mut, monkeypatch)
    assert open(p, 'rb').read()[-20] == open(SRC, 'rb').read()[-20] ^ 1
    assert os.listdir(tmp_path) == ['a.3dm']

def test_touch_only_refused_untouched(tmp_path, monkeypatch):
    p = _run(tmp_path, lambda p: os.utime(p, ns=(1, 1)), monkeypatch)
    assert open(p, 'rb').read() == open(SRC, 'rb').read() and os.listdir(tmp_path) == ['a.3dm']

def test_replaced_by_new_file(tmp_path, monkeypatch):
    def mut(p):
        t = p + '.new'; open(t, 'wb').write(b'other tool output'); os.replace(t, p)
    p = _run(tmp_path, mut, monkeypatch)
    assert open(p, 'rb').read() == b'other tool output' and os.listdir(tmp_path) == ['a.3dm']
