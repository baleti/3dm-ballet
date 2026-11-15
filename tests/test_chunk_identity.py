import glob, os, shutil, struct, pytest
import rhino3dm as R
from tm3dballet import write
D = os.path.join(os.path.dirname(__file__), 'data')
FILES = sorted(glob.glob(os.path.join(D, 'V[67]*.3dm')))

def tops(b):
    o = 32; out = []
    while o + 12 <= len(b):
        t, l = struct.unpack_from('<Iq', b, o); out.append((t, b[o:o + 12 + l]))
        if t == 0x7fff: break
        o += 12 + l
    return out

@pytest.mark.parametrize('f', FILES, ids=os.path.basename)
def test_only_layer_and_properties_chunks_change_and_one_layer_record(f, tmp_path):
    p = str(tmp_path / 'a.3dm'); shutil.copy(f, p); src = open(p, 'rb').read()
    try: lay = R.File3dm.Read(p).Layers[0].Name
    except Exception: pytest.skip('unreadable')
    try: write.rename_layer(p, lay, 'Zq1')
    except write.Refused: pytest.skip('refused by design')
    a, b = tops(src), tops(open(p, 'rb').read())
    assert [t for t, _ in a] == [t for t, _ in b], 'top-level chunk list changed'
    changed = {t for (t, x), (_, y) in zip(a, b) if x != y and t != 0x7fff}
    assert changed <= {0x10000011, 0x10000014}, [hex(t) for t in changed]          # everything else byte-identical (geometry, materials, settings, ...)
    ra = write._table_records(src, 0x10000011); rb = write._table_records(open(p, 'rb').read(), 0x10000011)
    assert len(ra[2]) == len(rb[2])
    diff = [i for i, (x, y) in enumerate(zip(ra[2], rb[2])) if x[3] != y[3]]
    assert len(diff) <= 1, diff       # only the renamed layer's record (the first layer here)
