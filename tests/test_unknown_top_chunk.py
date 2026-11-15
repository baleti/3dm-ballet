import os, struct, pytest
import rhino3dm as R
from tm3dballet import write
D = os.path.dirname(__file__)
SAMPLES = ['data/V7-v7_my_brep.3dm', 'data/V6-my_mesh_with_material.3dm', 'data/V6-my_viewports.3dm']
MARK = b'FOREIGN-TOP-LEVEL-CHUNK'

def _insert(src, dst, before_table, code):
    b = open(src, 'rb').read(); o = 32; at = None
    while o + 12 <= len(b):
        t, l = struct.unpack_from('<Iq', b, o)
        if t == before_table or t == 0x7fff: at = o; break
        o += 12 + l
    if at is None: return False
    ch = struct.pack('<Iq', code, len(MARK)) + MARK
    out = bytearray(b[:at] + ch + b[at:]); struct.pack_into('<q', out, len(out) - 8, len(out)); open(dst, 'wb').write(bytes(out)); return True

@pytest.mark.parametrize('code', [0x10000099, 0x00000123, 0x20008099])
@pytest.mark.parametrize('before', [0x10000011, 0x10000013, 0x7fff], ids=hex)
@pytest.mark.parametrize('sample', SAMPLES, ids=os.path.basename)
def test_foreign_top_level_chunk_kept_or_refused(sample, before, code, tmp_path):
    p = str(tmp_path / 'a.3dm')
    if not _insert(os.path.join(D, sample), p, before, code): pytest.skip('anchor absent')
    orig = open(p, 'rb').read()
    try:
        m = R.File3dm.Read(p)
        if m is None: pytest.skip('library rejects the synthetic source')
        old = m.Layers[0].Name
    except Exception: pytest.skip('unreadable')
    try: write.rename_layer(p, old, 'Zed')
    except write.Refused: assert open(p, 'rb').read() == orig and os.listdir(tmp_path) == ['a.3dm']; return
    assert MARK in open(p, 'rb').read(), 'unknown top-level chunk silently dropped (ESCAPE)'
    assert R.File3dm.Read(p).Layers[0].Name == 'Zed' and open(p + '.bak', 'rb').read() == orig
