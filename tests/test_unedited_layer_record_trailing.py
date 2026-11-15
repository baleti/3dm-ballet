import os, struct, pytest
import rhino3dm as R
from tm3dballet import write

def _make(path, which, extra):
    m = R.File3dm()
    for n in ('A', 'B', 'C'):
        l = R.Layer(); l.Name = n; m.Layers.Add(l)
    m.Objects.AddPoint(R.Point3d(1, 2, 3)); assert m.Write(path, 7)
    b = bytearray(open(path, 'rb').read()); o, l, recs = write._table_records(bytes(b), 0x10000011)
    r, tot, tc, pay = [x for x in recs if x[2] == 0x20008050][which]
    b[r + 4:r + 12] = struct.pack('<q', len(pay) + len(extra)); b[r + tot:r + tot] = extra
    b[o + 4:o + 12] = struct.pack('<q', l + len(extra)); struct.pack_into('<q', b, len(b) - 8, len(b))
    open(path, 'wb').write(bytes(b))

@pytest.mark.parametrize('which', [0, 1, 2])
@pytest.mark.parametrize('target', ['A', 'B', 'C'])
def test_trailing_data_in_one_record_rename_another_or_same(which, target, tmp_path):
    p = str(tmp_path / 'a.3dm'); _make(p, which, b'UNKNOWN-PLUGIN-DATA')
    orig = open(p, 'rb').read()
    if R.File3dm.Read(p) is None or write.structure_problem(p): pytest.skip('synthetic source not accepted')
    try: write.rename_layer(p, target, 'Zed')
    except write.Refused: assert open(p, 'rb').read() == orig and os.listdir(tmp_path) == ['a.3dm']; return
    assert b'UNKNOWN-PLUGIN-DATA' in open(p, 'rb').read(), 'unknown record data silently dropped'
    assert open(p + '.bak', 'rb').read() == orig
