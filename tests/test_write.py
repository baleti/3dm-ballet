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


def test_view_change_detected():
    import rhino3dm as R, glob, os
    from tm3dballet import write
    f = os.path.join(os.path.dirname(__file__), 'data', 'V7-v7_my_viewports.3dm')
    m = R.File3dm.Read(f); s1 = write.snapshot(m)
    assert len(s1['views']) == 7 and s1['views'][0][0] != 'unreadable'
    s3 = dict(s1); s3['views'] = [list(v) for v in s1['views']]; s3['views'][2][2] = (9.0, 9.0, 9.0)  # camera moved
    assert any('views' in d for d in write.diff(s1, s3))
    other = write.snapshot(R.File3dm.Read(os.path.join(os.path.dirname(f), 'V8-v8_caps_and_joins.3dm')))
    assert any('views' in d for d in write.diff(s1, other))
    m2 = R.File3dm.Read(f)
    assert write.diff(s1, write.snapshot(m2)) == []


def test_second_edit_keeps_first_backup_and_mode(tmp_path):
    f = str(tmp_path / 'a.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f); os.chmod(f, 0o644)
    orig = open(f, 'rb').read(); lay = R.File3dm.Read(f).Layers[0].Name
    write.rename_layer(f, lay, lay + '_1'); write.rename_layer(f, lay + '_1', lay + '_2')
    assert open(f + '.bak', 'rb').read() == orig          # the true original survives the second edit
    assert os.path.exists(f + '.bak.1') and open(f + '.bak.1', 'rb').read() != orig
    if os.name == 'posix': assert os.stat(f).st_mode & 0o777 == 0o644
    assert R.File3dm.Read(f).Layers[0].Name == lay + '_2'


@pytest.mark.parametrize('where', ['mid_write', 'before_replace'])
def test_process_killed_mid_save_leaves_original_identical(where, tmp_path):
    """hard kill (no finally blocks) during the save: original byte-identical and still loadable"""
    import subprocess, sys, textwrap
    f = str(tmp_path / 'a.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f); before = open(f, 'rb').read()
    root = os.path.dirname(os.path.dirname(__file__)); lay = R.File3dm.Read(f).Layers[0].Name
    code = textwrap.dedent('''
        import sys, os
        sys.path[:0] = [%r, %r]
        from tm3dballet import write
        where = %r
        if where == 'mid_write':
            def gw(m, tmp, ver, timeout=120):
                open(tmp, 'wb').write(b'3D Geometry File Format ' + b'\\0' * 7); os._exit(9)
            write._guarded_write = gw
        else:
            def rep(a, b): os._exit(9)
            write.os.replace = rep
        write.rename_layer(%r, %r, 'zzz')
    ''') % (root, os.path.join(root, '.deps'), where, f, lay)
    r = subprocess.run([sys.executable, '-I', '-c', code], timeout=120)
    assert r.returncode == 9
    assert open(f, 'rb').read() == before
    assert R.File3dm.Read(f).Layers[0].Name == lay


def test_dangling_bak_symlink_not_followed(tmp_path):
    if os.name != 'posix': pytest.skip('symlinks')
    f = str(tmp_path / 'a.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f)
    victim = tmp_path / 'victim.txt'; os.symlink(str(victim), f + '.bak')   # dangling
    orig = open(f, 'rb').read(); lay = R.File3dm.Read(f).Layers[0].Name
    write.rename_layer(f, lay, lay + '_x')
    assert not victim.exists() and os.path.islink(f + '.bak')
    assert open(f + '.bak.1', 'rb').read() == orig


def test_readonly_directory_refused_original_intact(tmp_path):
    if os.name != 'posix' or os.geteuid() == 0: pytest.skip('needs posix non-root')
    d = tmp_path / 'ro'; d.mkdir(); f = str(d / 'a.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f)
    before = open(f, 'rb').read(); lay = R.File3dm.Read(f).Layers[0].Name
    os.chmod(d, 0o555)
    try:
        with pytest.raises(write.Refused): write.rename_layer(f, lay, lay + '_x')
    finally: os.chmod(d, 0o755)
    assert open(f, 'rb').read() == before and os.listdir(d) == ['a.3dm']


@pytest.mark.parametrize('kind', ['dir', 'fifo'])
def test_non_regular_source_refused_nothing_created(kind, tmp_path):
    if os.name != 'posix': pytest.skip('posix')
    p = tmp_path / 'x.3dm'
    if kind == 'dir': p.mkdir()
    else: os.mkfifo(str(p))
    with pytest.raises(write.Refused): write.rename_layer(str(p), 'a', 'b')
    assert os.listdir(tmp_path) == ['x.3dm']


def test_kill_mid_save_unicode_space_path(tmp_path):
    import subprocess, sys
    d = tmp_path / 'café modèle 1'; d.mkdir(); f = str(d / 'plän final.3dm')
    shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f); before = open(f, 'rb').read(); lay = R.File3dm.Read(f).Layers[0].Name
    root = os.path.dirname(os.path.dirname(__file__))
    code = ('import sys,os\nsys.path[:0]=[%r,%r]\nfrom tm3dballet import write\n'
            'write.os.replace = lambda a, b: os._exit(9)\nwrite.rename_layer(%r, %r, "zzz")\n') % (root, os.path.join(root, '.deps'), f, lay)
    assert subprocess.run([sys.executable, '-I', '-c', code], timeout=120).returncode == 9
    assert open(f, 'rb').read() == before
