import os, struct, pytest
import rhino3dm as R
from tm3dballet import write
D = os.path.dirname(__file__)
SAMPLES = ['data/V7-v7_my_brep.3dm', 'data/V6-my_mesh.3dm']
TABLES = [0x10000011, 0x10000013]
MUT = {'rec_len+1': (4, 1), 'rec_len-1': (4, -1), 'rec_len+1M': (4, 1 << 20), 'rec_len=0': (4, None), 'table_len+1': (-8, 1), 'table_len-1': (-8, -1), 'table_len+8': (-8, 8)}

@pytest.mark.parametrize('mut', MUT)
@pytest.mark.parametrize('table', TABLES, ids=hex)
@pytest.mark.parametrize('sample', SAMPLES, ids=os.path.basename)
def test_length_field_damage_never_saved_silently(sample, table, mut, tmp_path):
    src = open(os.path.join(D, sample), 'rb').read(); t = write._table_records(src, table)
    if t is None: pytest.skip('table absent')
    b = bytearray(src); off, delta = MUT[mut]
    if off == 4:
        recs = [r for r in t[2] if r[1] > 20]
        if not recs: pytest.skip('no sizeable record')
        pos = recs[0][0] + 4; v = struct.unpack_from('<q', b, pos)[0]; struct.pack_into('<q', b, pos, 0 if delta is None else v + delta)
    else:
        pos = t[0] + 4; v = struct.unpack_from('<q', b, pos)[0]; struct.pack_into('<q', b, pos, v + delta)
    b = bytes(b); p = str(tmp_path / 'a.3dm'); open(p, 'wb').write(b)
    try:
        m = R.File3dm.Read(p)
        if m is None: pytest.skip('library rejects mutated source')
        old = m.Layers[0].Name
    except Exception: pytest.skip('library rejects mutated source')
    try: write.rename_layer(p, old, old + 'Q')
    except write.Refused: assert open(p, 'rb').read() == b and os.listdir(tmp_path) == ['a.3dm']; return
    pytest.fail('save accepted a file with a damaged length field (ESCAPE); library read it as %d layers' % len(R.File3dm.Read(p).Layers))
