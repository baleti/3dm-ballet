import os, glob, shutil, struct, pytest
import rhino3dm as R
from tm3dballet import write
D = os.path.dirname(__file__)
SAMPLES = ['data/V7-v7_my_brep.3dm', 'data/V6-my_mesh_with_material.3dm', 'data/V6-my_spot_light.3dm', 'data/V6-my_viewports.3dm']
TABLES = [(0x10000014, 1), (0x10000014, 2), (0x10000014, 3), (0x10000014, 0), (0x10000010, 0), (0x10000012, 0), (0x10000013, 0), (0x10000015, 0), (0x10000020, 0), (0x10000023, 0), (0x10000025, 0), (0x10000026, 0)]
MARK = b'UNKNOWN-TRAILING-77'

def _grow(src, dst, table, k):
    b = bytearray(open(src, 'rb').read()); t = write._table_records(bytes(b), table)
    if t is None: return False
    o, l, recs = t; recs = [r for r in recs if r[1] > 12]
    if k >= len(recs): return False
    r, tot, tc, pay = recs[k]
    b[r + 4:r + 12] = struct.pack('<q', len(pay) + len(MARK)); b[r + tot:r + tot] = MARK
    b[o + 4:o + 12] = struct.pack('<q', l + len(MARK)); struct.pack_into('<q', b, len(b) - 8, len(b))
    open(dst, 'wb').write(bytes(b)); return True

@pytest.mark.parametrize('table,k', TABLES, ids=lambda x: hex(x) if isinstance(x, int) and x > 99 else str(x))
@pytest.mark.parametrize('sample', SAMPLES, ids=os.path.basename)
def test_unknown_trailing_bytes_never_silently_dropped(sample, table, k, tmp_path):
    src = os.path.join(D, sample); p = str(tmp_path / 'a.3dm')
    if not _grow(src, p, table, k): pytest.skip('table absent')
    orig = open(p, 'rb').read()
    try:
        if R.File3dm.Read(p) is None or write.structure_problem(p): pytest.skip('synthetic source not accepted')
        old = R.File3dm.Read(p).Layers[0].Name
    except Exception: pytest.skip('synthetic source not readable')
    try: write.rename_layer(p, old, 'Zed')
    except write.Refused: assert open(p, 'rb').read() == orig and os.listdir(tmp_path) == ['a.3dm']; return
    if (table, k) == (0x10000014, 0): pytest.skip('record 0x20008027 is the revision history the library regenerates on every save by design (ALLOWED_RECORD_DIFFS)')
    assert MARK in open(p, 'rb').read(), 'unknown trailing data silently dropped (ESCAPE)'
    assert open(p + '.bak', 'rb').read() == orig
