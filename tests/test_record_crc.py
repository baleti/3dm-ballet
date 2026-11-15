import glob, os, shutil, struct, zlib, pytest
import rhino3dm as R
from tm3dballet import write
D = os.path.join(os.path.dirname(__file__), 'data')
FILES = sorted(glob.glob(os.path.join(D, 'V[67]*.3dm')) + glob.glob(os.path.join(D, '..', 'data_ext', '*.3dm')))

def crc_status(path):
    """{(table, typecode, nth): crc_ok} for every CRC-bearing record (typecode bit 0x8000) of the property and settings tables.
    Object and layer records carry no usable CRC in these files (field is 0), so they are not judged here."""
    b = open(path, 'rb').read(); o = 32; out = {}
    while o + 12 <= len(b):
        t, l = struct.unpack_from('<Iq', b, o)
        if t == 0x7fff: break
        if t in (0x10000014, 0x10000015):
            r = o + 12; end = o + 12 + l; n = {}
            while r + 12 <= end:
                t2, l2 = struct.unpack_from('<Iq', b, r)
                if t2 & 0x80000000: r += 12; continue
                if t2 & 0x8000 and l2 >= 4:
                    k = n.get(t2, 0); n[t2] = k + 1
                    out[(t, t2, k)] = zlib.crc32(b[r + 12:r + 12 + l2 - 4]) & 0xffffffff == struct.unpack_from('<I', b, r + 12 + l2 - 4)[0]
                r += 12 + l2
        o += 12 + l
    return out

@pytest.mark.parametrize('f', FILES, ids=os.path.basename)
def test_saved_file_keeps_valid_record_crcs(f, tmp_path):
    p = str(tmp_path / 'a.3dm'); shutil.copy(f, p); src = crc_status(p)
    try: lay = R.File3dm.Read(p).Layers[0].Name
    except Exception: pytest.skip('unreadable')
    try: write.rename_layer(p, lay, 'Zq1')
    except write.Refused: pytest.skip('refused by design')
    after = crc_status(p)
    extra = set(after) - set(src)
    assert set(src) <= set(after) and all(k[1] == 0x20008027 and after[k] for k in extra), extra   # library may add the as-file-name record (0x20008027), with a valid CRC
    broke = [k for k in src if src[k] and not after[k]]
    assert not broke, [(hex(a), hex(b), c) for a, b, c in broke]
