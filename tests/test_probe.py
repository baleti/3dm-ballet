import os, pytest
from tm3dballet import probe, reader, write
HERE = os.path.dirname(os.path.abspath(__file__))
HANG = os.path.join(HERE, 'regress', 'hang_v7_surfaces_zeroed.3dm')

def test_hang_file_rejected_not_hung():
    with pytest.raises(probe.Unreadable): probe.probe(HANG, timeout=5)

def test_reader_load_guarded():
    with pytest.raises(probe.Unreadable): reader.load(HANG)

def test_write_refuses_and_original_untouched(tmp_path):
    f = tmp_path / 'a.3dm'; f.write_bytes(open(HANG, 'rb').read()); before = f.read_bytes()
    with pytest.raises(write.Refused): write.edit_file(str(f), lambda m: None, lambda d: True)
    assert f.read_bytes() == before and not os.path.exists(str(f) + '.bak')

def test_adapter_rejects_hang_bytes():
    from tm3dballet.sgadapter import Dm3Adapter
    a = Dm3Adapter(); buf = open(HANG, 'rb').read()
    assert a.sniff(buf) is None
    with pytest.raises(Exception): a.validate(buf)

def test_source_modified_during_edit_refused(tmp_path):
    import glob
    src = sorted(glob.glob(os.path.join(HERE, 'data', 'V8-*.3dm')))[0]
    f = tmp_path / 'a.3dm'; f.write_bytes(open(src, 'rb').read())
    def edit(m):
        m.Layers[0].Name = 'zz_renamed'
        with open(str(f), 'ab') as h: h.write(b'\0')   # someone else touches the file mid-edit
    with pytest.raises(write.Refused, match='changed'):
        write.edit_file(str(f), edit, lambda d: True)
    assert f.read_bytes().endswith(b'\0') and not os.path.exists(str(f) + '.bak')
    assert [p.name for p in tmp_path.iterdir()] == ['a.3dm']


def _good(tmp_path):
    import glob
    src = sorted(glob.glob(os.path.join(HERE, 'data', 'V8-*.3dm')))[0]
    f = tmp_path / 'a.3dm'; f.write_bytes(open(src, 'rb').read()); return f

def test_readonly_directory_refused_original_intact(tmp_path):
    if os.name == 'nt' or os.geteuid() == 0: pytest.skip('posix non-root only')
    f = _good(tmp_path); before = f.read_bytes(); os.chmod(tmp_path, 0o555)
    try:
        with pytest.raises(write.Refused): write.edit_file(str(f), lambda m: None, lambda d: True)
    finally: os.chmod(tmp_path, 0o755)
    assert f.read_bytes() == before

def test_write_failure_and_replace_failure_leave_original(tmp_path, monkeypatch):
    f = _good(tmp_path); before = f.read_bytes()
    monkeypatch.setattr(os, 'replace', lambda a, b: (_ for _ in ()).throw(OSError(28, 'No space left on device')))
    with pytest.raises(write.Refused, match='replace failed'): write.edit_file(str(f), lambda m: None, lambda d: True)
    monkeypatch.undo()
    assert f.read_bytes() == before
    assert [p.name for p in tmp_path.iterdir() if p.name.endswith('.3dm') and p.name != 'a.3dm'] == []

def test_backup_failure_refuses_before_replace(tmp_path, monkeypatch):
    f = _good(tmp_path); before = f.read_bytes()
    monkeypatch.setattr(write.shutil, 'copy2', lambda a, b: (_ for _ in ()).throw(OSError(28, 'No space left')))
    with pytest.raises(write.Refused, match='backup failed'): write.edit_file(str(f), lambda m: None, lambda d: True)
    monkeypatch.undo()
    assert f.read_bytes() == before


def test_probe_cache_hits_and_invalidates(tmp_path, monkeypatch):
    f = _good(tmp_path); calls = []
    real = probe._probe
    monkeypatch.setattr(probe, '_probe', lambda p, t: (calls.append(p), real(p, t))[1])
    probe._OK.clear()
    probe.probe(str(f)); probe.probe(str(f)); assert len(calls) == 1
    with open(str(f), 'ab') as h: h.write(b'\0')          # file changed: must re-probe
    probe.probe(str(f)); assert len(calls) == 2
    h2 = tmp_path / 'hang.3dm'; h2.write_bytes(open(HANG, 'rb').read())
    for _ in range(2):
        with pytest.raises(probe.Unreadable): probe.probe(str(h2), timeout=5)
    assert len(calls) == 4                                  # failures are never cached


def test_stalled_native_write_refused_original_intact(tmp_path, monkeypatch):
    import time, rhino3dm as R
    f = _good(tmp_path); before = f.read_bytes()
    monkeypatch.setattr(write, 'WRITE_TIMEOUT', 1)
    class Slow:
        def __init__(self, m): self._m = m
        def __getattr__(self, n): return getattr(self._m, n)
        def Write(self, p, v): time.sleep(5); return True
    real = R.File3dm.Read
    monkeypatch.setattr(write.R.File3dm, 'Read', staticmethod(lambda p: Slow(real(p))))
    with pytest.raises(write.Refused, match='timed out'): write.edit_file(str(f), lambda m: None, lambda d: True)
    monkeypatch.undo(); time.sleep(5)
    assert f.read_bytes() == before and [p.name for p in tmp_path.iterdir()] == ['a.3dm']


@pytest.mark.parametrize('name', ['plan é ü 日本語.3dm', 'with space and (parens) [1].3dm', "quote'and,comma;.3dm", 'a' * 120 + '.3dm'])
def test_unicode_and_odd_filenames(tmp_path, name):
    f = _good(tmp_path); g = tmp_path / name; f.rename(g); before = g.read_bytes()
    reader.info(str(g))
    ds = write.edit_file(str(g), lambda m: None, lambda d: d == [])
    assert ds == [] and os.path.exists(str(g) + '.bak') and open(str(g) + '.bak', 'rb').read() == before
    probe.probe(str(g))


def test_symlink_target_is_edited_link_preserved(tmp_path):
    if os.name == 'nt': pytest.skip('posix symlinks')
    real = _good(tmp_path); (tmp_path / 'sub').mkdir()
    link = tmp_path / 'sub' / 'link.3dm'; os.symlink(str(real), str(link))
    write.edit_file(str(link), lambda m: None, lambda d: d == [])
    assert os.path.islink(str(link)) and os.path.realpath(str(link)) == str(real)
    assert [p.name for p in (tmp_path / 'sub').iterdir() if p.name != 'link.3dm'] == []


def test_hardlinked_file_refused(tmp_path):
    if os.name == 'nt': pytest.skip('posix hardlinks')
    f = _good(tmp_path); os.link(str(f), str(tmp_path / 'other.3dm')); before = f.read_bytes()
    with pytest.raises(write.Refused, match='hard link'): write.edit_file(str(f), lambda m: None, lambda d: True)
    assert f.read_bytes() == before and (tmp_path / 'other.3dm').read_bytes() == before
