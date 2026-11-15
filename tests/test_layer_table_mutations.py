import os, random, struct, pytest
import rhino3dm as R
from tm3dballet import write
D = os.path.dirname(__file__)
SAMPLES = ['data/V7-v7_my_brep.3dm', 'data/V6-my_mesh_with_material.3dm', 'data/V8-v8_section_hatch.3dm']

def _lay(m): return [(str(l.Id), str(l.ParentLayerId), l.Name, l.Visible, l.Locked, tuple(l.Color), l.LinetypeIndex, l.PlotWeight) for l in m.Layers]

@pytest.mark.parametrize('seed', range(12))
@pytest.mark.parametrize('sample', SAMPLES, ids=os.path.basename)
def test_flip_inside_layer_records(sample, seed, tmp_path):
    rnd = random.Random(seed * 7919 + 1); src = open(os.path.join(D, sample), 'rb').read()
    t = write._table_records(src, 0x10000011)
    if t is None: pytest.skip('no layer table')
    recs = [r for r in t[2] if r[2] == 0x20008050 and r[1] > 20]
    r = rnd.choice(recs); pos = r[0] + 12 + rnd.randrange(len(r[3])); b = bytearray(src); b[pos] ^= 1 << rnd.randrange(8)
    p = str(tmp_path / 'a.3dm'); open(p, 'wb').write(bytes(b)); orig = bytes(b)
    try:
        m = R.File3dm.Read(p)
        if m is None: pytest.skip('library rejects mutated source')
        before = _lay(m); old = m.Layers[0].Name
    except Exception: pytest.skip('library rejects mutated source')
    try: write.rename_layer(p, old, old + 'Q')
    except write.Refused: assert open(p, 'rb').read() == orig and os.listdir(tmp_path) == ['a.3dm']; return
    after = _lay(R.File3dm.Read(p)); want = [(a[0], a[1], a[2] + 'Q' if i == 0 else a[2]) + a[3:] for i, a in enumerate(before)]
    assert after == want, 'mutated layer record accepted and then read back differently (ESCAPE)'
    assert open(p + '.bak', 'rb').read() == orig
