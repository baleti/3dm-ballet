import os, shutil, pytest
import rhino3dm as R
from tm3dballet import write
import test_trailing_other_tables as T   # reuses the record-growing helper

SAMPLES = ['data/V7-v7_my_brep.3dm', 'data/V6-my_mesh.3dm', 'data/V6-my_surfaces.3dm', 'data/V6-my_curves.3dm']

@pytest.mark.parametrize('k', range(4))
@pytest.mark.parametrize('sample', SAMPLES, ids=os.path.basename)
def test_unknown_bytes_in_object_record_k_kept(sample, k, tmp_path):
    p = str(tmp_path / 'a.3dm')
    if not T._grow(os.path.join(T.D, sample), p, 0x10000013, k): pytest.skip('fewer objects')
    orig = open(p, 'rb').read(); old = R.File3dm.Read(p).Layers[0].Name
    try: write.rename_layer(p, old, 'Zed')
    except write.Refused: assert open(p, 'rb').read() == orig and os.listdir(tmp_path) == ['a.3dm']; return
    assert T.MARK in open(p, 'rb').read(), 'object record data silently dropped'
    assert open(p + '.bak', 'rb').read() == orig
