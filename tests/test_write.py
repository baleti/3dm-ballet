import glob, os, shutil, pytest
import rhino3dm as R
from tm3dballet import write
D = os.path.join(os.path.dirname(__file__), 'data')
FILES = sorted(glob.glob(os.path.join(D, '*.3dm')))

def names(p): return [l.Name for l in R.File3dm.Read(p).Layers]

def test_rename_layer_roundtrip(tmp_path):
    f = str(tmp_path / 'a.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f)
    ds = write.rename_layer(f, 'brep', 'Renamed')
    assert ds == ['layers differs'] and names(f) == ['Renamed'] and names(f + '.bak') == ['brep']

def test_refuses_missing_layer_and_leaves_original(tmp_path):
    f = str(tmp_path / 'a.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f)
    before = open(f, 'rb').read()
    with pytest.raises(write.Refused): write.rename_layer(f, 'nope', 'x')
    assert open(f, 'rb').read() == before and os.listdir(tmp_path) == ['a.3dm']

def test_gate_catches_unintended_change(tmp_path):
    f = str(tmp_path / 'a.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f)
    before = open(f, 'rb').read()
    def evil(m): m.Layers[0].Name = 'x'; m.Objects[0].Attributes.Name = 'sneaky'  # attribute edit not allowed by expect
    # attribute edits on a copy of Objects are not written back by rhino3dm, so also force a layer + count mismatch
    with pytest.raises(write.Refused): write.edit_file(f, lambda m: (evil(m), m.Layers.Add(R.Layer())), lambda ds: ds == ['layers differs'])
    assert open(f, 'rb').read() == before

# files whose no-edit rewrite by rhino3dm is NOT equivalent: the gate must refuse them (regression set, severity 1 if ever accepted)
KNOWN_LOSSY = {'V5-v5_example_file.3dm': 'annotation geometry differs after rewrite',
               'V7-v7_rhino_logo_annotations.3dm': 'one opaque plug-in data block dropped'}

@pytest.mark.parametrize('f', FILES, ids=os.path.basename)
def test_noedit_roundtrip_equivalent(f, tmp_path):
    """load, save with no edit, re-read: semantic snapshot must be identical, else the file must be a known lossy case"""
    m = R.File3dm.Read(f)
    if write.gate(m): pytest.skip('gate refuses: %s' % write.gate(m))
    o = str(tmp_path / 'o.3dm'); assert m.Write(o, m.ArchiveVersion)
    d = write.diff(write.snapshot(m), write.snapshot(R.File3dm.Read(o)))
    assert (d != []) == (os.path.basename(f) in KNOWN_LOSSY), d[:3]

@pytest.mark.parametrize('name', sorted(KNOWN_LOSSY))
def test_lossy_files_are_refused_and_untouched(name, tmp_path):
    f = str(tmp_path / name); shutil.copy(os.path.join(D, name), f); before = open(f, 'rb').read()
    lay = R.File3dm.Read(f).Layers[0].Name
    with pytest.raises(write.Refused): write.rename_layer(f, lay, lay + '_x')
    assert open(f, 'rb').read() == before and not os.path.exists(f + '.bak')


def test_user_strings_in_snapshot_and_dropped_string_detected():
    import rhino3dm as R
    from tm3dballet import write
    m = R.File3dm(); m.Settings.ModelUnitSystem = R.UnitSystem.Meters
    a = R.ObjectAttributes(); a.SetUserString('k', 'v')
    m.Objects.AddPoint(R.Point3d(1, 2, 3), a)
    s1 = write.snapshot(m)
    o = next(iter(s1['objects'].values()))
    assert o['ustr'] == [('k', 'v')]
    m.Objects[0].Attributes.SetUserString('k', 'changed')
    ds = write.diff(s1, write.snapshot(m))
    assert any('ustr' in d for d in ds)
