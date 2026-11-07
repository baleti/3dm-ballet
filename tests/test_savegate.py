import json, os, shutil
import pytest
sg = pytest.importorskip('savegate')
import rhino3dm as R
from savegate import errors
from tm3dballet.sgadapter import Dm3Adapter, serialize
D = os.path.join(os.path.dirname(__file__), 'data')

def mk(tmp_path, name='V7-v7_my_brep.3dm'):
    f = str(tmp_path / 'a.3dm'); shutil.copy(os.path.join(D, name), f); return f

def renamed(f, new='Renamed'):
    m = R.File3dm.Read(f); m.Layers[0].Name = new; return serialize(m)

def cfg(tmp_path, allow=False, gate=False):
    gp = str(tmp_path / 'gate.json'); json.dump({'3dm': {'v70': 'open'}} if gate else {}, open(gp, 'w'))
    return sg.Config(allow_overwrite=allow, gate_file=gp, journal_dir=str(tmp_path / 'j'))

def test_save_as_ok_and_source_untouched(tmp_path):
    f = mk(tmp_path); before = open(f, 'rb').read(); out = str(tmp_path / 'b.3dm')
    with sg.open_doc(f, Dm3Adapter(), cfg(tmp_path)) as doc:
        assert doc.version == 'v70'
        r = sg.save_as(doc, renamed(f), out, {'modified': ['layers']})
    assert r.ok and open(f, 'rb').read() == before and R.File3dm.Read(out).Layers[0].Name == 'Renamed'

def test_undeclared_change_rejected(tmp_path):
    f = mk(tmp_path); out = str(tmp_path / 'b.3dm')
    m = R.File3dm.Read(f); m.Layers[0].Name = 'x'; m.Layers.Add(R.Layer()); bad = serialize(m)
    with sg.open_doc(f, Dm3Adapter(), cfg(tmp_path)) as doc:
        with pytest.raises(errors.VerifyFailed): sg.save_as(doc, bad, out, {'modified': []})
        with pytest.raises(errors.VerifyFailed): sg.save_as(doc, renamed(f), out, {'modified': []})   # declared nothing
    assert not os.path.exists(out)

def test_undeclared_added_object_rejected(tmp_path):
    f = mk(tmp_path, 'V7-v7_my_mesh.3dm'); out = str(tmp_path / 'b.3dm')
    m = R.File3dm.Read(f); m.Objects.AddPoint(R.Point3d(1, 2, 3))
    with sg.open_doc(f, Dm3Adapter(), cfg(tmp_path)) as doc:
        with pytest.raises(errors.VerifyFailed): sg.save_as(doc, serialize(m), out, {'modified': []})
        assert sg.save_as(doc, serialize(m), out, {'modified': ['n_objects'], 'added': [k for k in doc.adapter.snapshot(serialize(m)) if k.startswith('obj:') and k not in doc.adapter.snapshot(doc.buf)]}).ok

def test_overwrite_closed_by_default_then_open(tmp_path):
    f = mk(tmp_path); before = open(f, 'rb').read(); new = renamed(f)
    with sg.open_doc(f, Dm3Adapter(), cfg(tmp_path)) as doc:
        with pytest.raises(errors.SaveError): sg.save(doc, new, {'modified': ['layers']})
    assert open(f, 'rb').read() == before
    with sg.open_doc(f, Dm3Adapter(), cfg(tmp_path, allow=True)) as doc:          # gate file closed
        with pytest.raises(errors.SaveError): sg.save(doc, new, {'modified': ['layers']})
    assert open(f, 'rb').read() == before
    c = cfg(tmp_path, allow=True, gate=True)
    with sg.open_doc(f, Dm3Adapter(), c) as doc:
        r = sg.save(doc, new, {'modified': ['layers']})
    assert r.ok and R.File3dm.Read(f).Layers[0].Name == 'Renamed'
    sg.restore(f)
    assert open(f, 'rb').read() == before

@pytest.mark.parametrize('name', ['V5-v5_example_file.3dm', 'V7-v7_rhino_logo_annotations.3dm'])
def test_known_lossy_rewrite_rejected(name, tmp_path):
    f = mk(tmp_path, name); out = str(tmp_path / 'b.3dm')
    m = R.File3dm.Read(f); m.Layers[0].Name = 'zz'
    with sg.open_doc(f, Dm3Adapter(), cfg(tmp_path)) as doc:
        with pytest.raises(errors.VerifyFailed): sg.save_as(doc, serialize(m), out, {'modified': ['layers']})

def test_lost_object_rejected(tmp_path):
    f = mk(tmp_path, 'V7-v7_my_mesh.3dm'); out = str(tmp_path / 'b.3dm')
    m = R.File3dm.Read(f); m.Objects.Delete(m.Objects[0].Attributes.Id)
    if len(m.Objects) != 0: pytest.skip('rhino3dm delete not effective')
    with sg.open_doc(f, Dm3Adapter(), cfg(tmp_path)) as doc:
        with pytest.raises(errors.VerifyFailed): sg.save_as(doc, serialize(m), out, {'modified': []})
