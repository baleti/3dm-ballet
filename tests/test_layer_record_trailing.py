import os, shutil, struct, pytest
import rhino3dm as R
from tm3dballet import write
SRC = os.path.join(os.path.dirname(__file__), 'data', 'V7-v7_my_brep.3dm')

def _grow_layer_record(src, dst, extra):
    """append `extra` bytes at the end of the first layer record payload and fix the record, table and end-of-file lengths"""
    b = bytearray(open(src, 'rb').read()); o, l, recs = write._table_records(bytes(b), 0x10000011)
    r, tot, tc, pay = next(x for x in recs if x[2] == 0x20008050)
    b[r + 4:r + 12] = struct.pack('<q', len(pay) + len(extra))
    b[r + tot:r + tot] = extra
    b[o + 4:o + 12] = struct.pack('<q', l + len(extra))
    struct.pack_into('<q', b, len(b) - 8, len(b))
    open(dst, 'wb').write(bytes(b))

def test_trailing_bytes_inside_layer_record(tmp_path):
    p = str(tmp_path / 'a.3dm'); _grow_layer_record(SRC, p, b'PLUGIN-USERDATA-1234')
    orig = open(p, 'rb').read(); m = R.File3dm.Read(p)
    if m is None or write.structure_problem(p): pytest.skip('synthetic file not accepted as a source')
    try: write.rename_layer(p, 'brep', 'Renamed')
    except write.Refused as e: assert open(p, 'rb').read() == orig and os.listdir(tmp_path) == ['a.3dm']; return
    # if saved, the unknown bytes must still be present somewhere in the layer record, never silently dropped
    assert b'PLUGIN-USERDATA-1234' in open(p, 'rb').read(), 'unknown layer record data silently dropped'
    assert open(p + '.bak', 'rb').read() == orig
