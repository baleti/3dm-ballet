import glob, json, os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytest
from tm3dballet import reader
FILES = sorted(glob.glob(os.path.join(os.path.dirname(__file__), 'data', '*.3dm')))

def _glb_ok(p):
    d = open(p, 'rb').read()
    assert d[:4] == b'glTF' and struct.unpack('<I', d[8:12])[0] == len(d)
    n = struct.unpack('<I', d[12:16])[0]; return json.loads(d[20:20 + n])

def test_have_samples(): assert len(FILES) >= 20

@pytest.mark.parametrize('f', FILES, ids=os.path.basename)
def test_info_and_glb(f, tmp_path):
    i = reader.info(f)
    assert i['objects'] >= 0 and i['archive_version'] > 0
    st = reader.to_glb(f, str(tmp_path / 'o.glb'))
    g = _glb_ok(str(tmp_path / 'o.glb'))
    assert st['batches'] == len(g['meshes'])

def test_brep_wire_fallback(tmp_path):
    f = os.path.join(os.path.dirname(__file__), 'data', 'V7-v7_my_brep.3dm')
    st = reader.to_glb(f, str(tmp_path / 'o.glb')); assert st.get('wire') == 1 and st['batches'] == 1

def test_mesh_object(tmp_path):
    f = os.path.join(os.path.dirname(__file__), 'data', 'V7-v7_my_mesh.3dm')
    assert reader.to_glb(f, str(tmp_path / 'o.glb')).get('meshed', 0) >= 1

@pytest.mark.parametrize('f', FILES[:30], ids=os.path.basename)
def test_noedit_roundtrip_equivalent(f, tmp_path):
    """write-plan probe: load, rhino3dm Write, reload; summary must be identical (byte identity is NOT expected, see docs/FORMAT.md)"""
    import rhino3dm as R
    m = reader.load(f); o = str(tmp_path / 'r.3dm')
    if not m.Write(o, m.ArchiveVersion if m.ArchiveVersion in (50, 60, 70, 80) else 70): pytest.skip('write refused for version %s' % m.ArchiveVersion)
    a, b = reader.info(f), reader.info(o)
    for k in ('objects', 'types', 'layers', 'materials', 'groups', 'instance_definitions'): assert a[k] == b[k], k
