import os, struct, pytest
import rhino3dm as R
from tm3dballet import write
D = os.path.dirname(__file__)
SAMPLES = ['data/V7-v7_my_brep.3dm', 'data/V6-my_mesh_with_material.3dm']
TABLES = [0x10000010, 0x10000011, 0x10000012, 0x10000013, 0x10000014, 0x10000015, 0x10000020, 0x10000023]

def _dup(src, dst, table, mark):
    b = open(src, 'rb').read(); o = 32
    while o + 12 <= len(b):
        t, l = struct.unpack_from('<Iq', b, o)
        if t == table:
            chunk = b[o:o + 12 + l]; extra = chunk + mark       # second copy of the table chunk, followed by a distinguishable marker chunk
            out = bytearray(b[:o + 12 + l] + chunk + b[o + 12 + l:]); struct.pack_into('<q', out, len(out) - 8, len(out))
            open(dst, 'wb').write(bytes(out)); return chunk
        if t == 0x7fff: return None
        o += 12 + l

@pytest.mark.parametrize('table', TABLES, ids=hex)
@pytest.mark.parametrize('sample', SAMPLES, ids=os.path.basename)
def test_second_copy_of_a_top_level_table(sample, table, tmp_path):
    p = str(tmp_path / 'a.3dm'); chunk = _dup(os.path.join(D, sample), p, table, b'')
    if chunk is None: pytest.skip('table absent')
    orig = open(p, 'rb').read()
    try:
        m = R.File3dm.Read(p)
        if m is None: pytest.skip('library rejects the synthetic source')
        old = m.Layers[0].Name
    except Exception: pytest.skip('unreadable')
    try: write.rename_layer(p, old, 'Zed')
    except write.Refused: assert open(p, 'rb').read() == orig and os.listdir(tmp_path) == ['a.3dm']; return
    out = open(p, 'rb').read()
    assert R.File3dm.Read(p).Layers[0].Name == 'Zed'
    if table not in (0x10000011, 0x10000014): assert out.count(chunk) == 2, 'second copy of the table silently dropped (ESCAPE)'
    assert open(p + '.bak', 'rb').read() == orig
