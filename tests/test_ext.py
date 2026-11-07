"""Extra public samples (MIT, mcneel/rhino3dm); run tests/fetch_ext.sh first, skipped when absent."""
import glob, os, pytest
from tm3dballet import reader
D = os.path.join(os.path.dirname(__file__), 'data_ext')
FILES = sorted(glob.glob(os.path.join(D, '*.3dm')))
pytestmark = pytest.mark.skipif(not FILES, reason='run tests/fetch_ext.sh')

@pytest.mark.parametrize('f', FILES, ids=os.path.basename)
def test_ext_sweep(f, tmp_path):
    reader.info(f); reader.to_glb(f, str(tmp_path / 'o.glb'))

def test_real_blocks(tmp_path):
    f = os.path.join(D, 'rh_blocks.3dm')
    if not os.path.exists(f): pytest.skip('absent')
    st = reader.to_glb(f, str(tmp_path / 'o.glb'))
    assert st['instances'] == 2 and st['idef_member'] == 4 and st['wire'] == 8
