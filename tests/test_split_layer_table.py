import os, struct, pytest
import rhino3dm as R
from tm3dballet import write
MARK = b'UNKNOWN-IN-SECOND-CHUNK'

def _make(path, extra):
    m = R.File3dm()
    for n in ('A', 'B', 'C'):
        l = R.Layer(); l.Name = n; m.Layers.Add(l)
    m.Objects.AddPoint(R.Point3d(1, 2, 3)); assert m.Write(path, 7)
    b = bytes(open(path, 'rb').read()); o, l, recs = write._table_records(b, 0x10000011)
    lr = [r for r in recs if r[2] == 0x20008050]; cut = lr[-1][0]          # last layer record starts the second chunk
    first = b[o + 12:cut]; second = b[cut:o + 12 + l]
    if extra:   # unknown bytes at the end of the layer record sitting in the second chunk
        r = lr[-1]; pay = b[r[0] + 12:r[0] + r[1]]; hdr = struct.pack('<Iq', 0x20008050, len(pay) + len(extra))
        tail = b[r[0] + r[1]:o + 12 + l]; second = hdr + pay + extra + tail
    t = struct.pack('<Iq', 0x10000011, len(first)) + first + struct.pack('<Iq', 0x10000011, len(second)) + second
    out = bytearray(b[:o] + t + b[o + 12 + l:]); struct.pack_into('<q', out, len(out) - 8, len(out))
    open(path, 'wb').write(bytes(out))

@pytest.mark.parametrize('extra', [b'', MARK])
@pytest.mark.parametrize('target', ['A', 'B', 'C'])
def test_layer_table_in_two_chunks(extra, target, tmp_path):
    p = str(tmp_path / 'a.3dm'); _make(p, extra); orig = open(p, 'rb').read()
    m = R.File3dm.Read(p)
    seen = None if m is None else [l.Name for l in m.Layers]
    try: write.rename_layer(p, target, 'Zed')
    except write.Refused: assert open(p, 'rb').read() == orig and os.listdir(tmp_path) == ['a.3dm']; return
    out = open(p, 'rb').read()
    assert seen == ['A', 'B', 'C'], 'saved a file whose second layer-table chunk the library cannot see (layer C lost)'
    assert [l.Name for l in R.File3dm.Read(p).Layers] == [('Zed' if n == target else n) for n in 'ABC']
    if extra: assert MARK in out, 'unknown data in the second layer-table chunk silently dropped (ESCAPE)'
    assert open(p + '.bak', 'rb').read() == orig
