import os, rhino3dm as R, pytest
from tm3dballet import write, reader
MAGIC = b'3D Geometry File Format ' 

def blobs(tmp_path):
    m = R.File3dm(); p = str(tmp_path / 'empty_model.3dm'); assert m.Write(p, 7)
    yield p
    for n, b in [('zero', b''), ('one', b'3'), ('magic', MAGIC), ('magic_v7', MAGIC + b'      70'), ('zeros', b'\0' * 4096)]:
        q = str(tmp_path / (n + '.3dm')); open(q, 'wb').write(b); yield q

def test_empty_and_stub_files_refused_untouched(tmp_path):
    for p in blobs(tmp_path):
        before = open(p, 'rb').read()
        if p.endswith('empty_model.3dm'):    # no layer table on disk; the library presents a 'Default' layer, renaming it writes a valid one
            write.rename_layer(p, 'Default', 'X'); assert [l.Name for l in R.File3dm.Read(p).Layers] == ['X'] and open(p + '.bak', 'rb').read() == before
            os.remove(p + '.bak'); continue
        with pytest.raises(write.Refused): write.rename_layer(p, 'Default', 'X')
        assert open(p, 'rb').read() == before
        try: reader.info(p)
        except Exception as e: assert type(e).__name__ in ('Refused', 'Unreadable', 'ValueError', 'RuntimeError', 'OSError'), type(e)
    assert not [f for f in os.listdir(tmp_path) if '.bak' in f or 'lock' in f or f.endswith('.tmp') or f.startswith('.3dmballet')]
