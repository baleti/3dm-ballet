import os, random, pytest
import rhino3dm as R
from tm3dballet import write
D = os.path.dirname(__file__)
SAMPLES = ['data/V7-v7_my_brep.3dm', 'data/V6-my_mesh_with_material.3dm', 'data/V6-my_spot_light.3dm']
TABLES = [0x10000010, 0x10000012, 0x10000013]

def _chunk(b, table):
    t = write._table_records(b, table)
    return None if t is None else b[t[0]:t[0] + 12 + t[1]]

@pytest.mark.parametrize('seed', range(8))
@pytest.mark.parametrize('table', TABLES, ids=hex)
@pytest.mark.parametrize('sample', SAMPLES, ids=os.path.basename)
def test_flip_in_untouched_table_stays_exactly_as_it_was(sample, table, seed, tmp_path):
    rnd = random.Random(seed * 104729 + table); src = open(os.path.join(D, sample), 'rb').read()
    t = write._table_records(src, table)
    if t is None: pytest.skip('table absent')
    recs = [r for r in t[2] if r[1] > 20]
    if not recs: pytest.skip('no sizeable record')
    r = rnd.choice(recs); b = bytearray(src); b[r[0] + 12 + rnd.randrange(len(r[3]))] ^= 1 << rnd.randrange(8); b = bytes(b)
    p = str(tmp_path / 'a.3dm'); open(p, 'wb').write(b)
    try:
        m = R.File3dm.Read(p)
        if m is None: pytest.skip('library rejects mutated source')
        old = m.Layers[0].Name
    except Exception: pytest.skip('library rejects mutated source')
    try: write.rename_layer(p, old, old + 'Q')
    except write.Refused: assert open(p, 'rb').read() == b and os.listdir(tmp_path) == ['a.3dm']; return
    out = open(p, 'rb').read()
    assert _chunk(out, table) == _chunk(b, table), 'mutated record in a table the edit does not touch was changed or repaired by the save'
    assert R.File3dm.Read(p).Layers[0].Name == old + 'Q' and open(p + '.bak', 'rb').read() == b
