import tempfile, glob, os, shutil, pytest
import rhino3dm as R
from tm3dballet import write
D = os.path.join(os.path.dirname(__file__), 'data')
FILES = sorted(glob.glob(os.path.join(D, '*.3dm')) + glob.glob(os.path.join(D, '..', 'data_ext', '*.3dm')))

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
    """an edit that also touches geometry must be refused when only a layer change is expected (layer-only edits are accepted)"""
    f = str(tmp_path / 'a.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f)
    before = open(f, 'rb').read()
    def evil(m): m.Layers[0].Name = 'x'; m.Objects.AddPoint(R.Point3d(1, 2, 3))
    with pytest.raises(write.Refused): write.edit_file(f, evil, lambda ds: ds == ['layers differs'])
    assert open(f, 'rb').read() == before and os.listdir(tmp_path) == ['a.3dm']

def test_gate_catches_deleted_geometry(tmp_path):
    f = str(tmp_path / 'a.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f)
    before = open(f, 'rb').read()
    def evil(m): m.Layers[0].Name = 'x'; m.Objects.Delete(m.Objects[0].Attributes.Id)
    with pytest.raises(write.Refused): write.edit_file(f, evil, lambda ds: ds == ['layers differs'])
    assert open(f, 'rb').read() == before and os.listdir(tmp_path) == ['a.3dm']

# files whose no-edit rewrite by rhino3dm is NOT equivalent: the gate must refuse them (regression set, severity 1 if ever accepted)
KNOWN_LOSSY = {'V5-v5_example_file.3dm': 'annotation geometry differs after rewrite',
               'rh_sphereDecals.3dm': 'embedded file paths rewritten (backslash/drive normalised) on rewrite',
               'V5-v5_extrusions.3dm': 'legacy RDK xml upgraded (attributes added) on rewrite',
               'V7-v7_rhino_logo_annotations.3dm': 'one opaque plug-in data block dropped'}

@pytest.mark.parametrize('f', FILES, ids=os.path.basename)
def test_noedit_roundtrip_equivalent(f, tmp_path):
    """load, save with no edit, re-read: semantic snapshot must be identical, else the file must be a known lossy case"""
    m = R.File3dm.Read(f)
    if write.gate(m): pytest.skip('gate refuses: %s' % write.gate(m))
    s0 = write.snapshot(m)   # BEFORE Write: Write mutates RDK state in memory, a later snapshot would mask loss
    o = str(tmp_path / 'o.3dm'); assert m.Write(o, m.ArchiveVersion)
    d = write.diff(s0, write.snapshot(R.File3dm.Read(o)))
    assert (d != []) == (os.path.basename(f) in KNOWN_LOSSY), d[:3]

@pytest.mark.parametrize('name', sorted(KNOWN_LOSSY))
def test_lossy_files_are_refused_and_untouched(name, tmp_path):
    f = str(tmp_path / name); shutil.copy(next(q for q in FILES if os.path.basename(q) == name), f); before = open(f, 'rb').read()
    lay = R.File3dm.Read(f).Layers[0].Name
    try: write.rename_layer(f, lay, lay + '_x')
    except write.Refused:
        assert open(f, 'rb').read() == before and not os.path.exists(f + '.bak'); return
    # accepted is only legitimate when the save provably lost nothing: every record of the output equals the source except the renamed
    # layer record, the library-version marker (0xa0000026) and the revision-history record (0x20008027) the library always rewrites
    import collections, struct
    def recs(path):
        b = open(path, 'rb').read(); c = collections.Counter(); o = 32; seen = collections.Counter()
        while o + 12 <= len(b):
            t, l = struct.unpack_from('<Iq', b, o)
            if t == 0x7fff: break
            r = write._table_records(b, t, seen[t]); seen[t] += 1
            for x in (r[2] if r else []): c[(t, x[2], bytes(x[3]))] += 1
            o += 12 + l
        return c
    A, B = recs(os.path.join(os.path.dirname(f), name) if False else next(q for q in FILES if os.path.basename(q) == name)), recs(f)
    allowed = {(0x10000014, 0xa0000026), (0x10000014, 0x20008027), (0x10000011, 0x20008050)}
    assert not [k for k in (A - B) | (B - A) if (k[0], k[1]) not in allowed], 'accepted a lossy file: records lost or changed'
    assert sum(1 for k in A - B if k[:2] == (0x10000011, 0x20008050)) == 1


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


def test_source_modified_during_edit_is_not_overwritten(tmp_path):
    f = str(tmp_path / 'a.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f); lay = R.File3dm.Read(f).Layers[0].Name
    def edit(m):
        m.Layers[0].Name = lay + '_x'
        with open(f, 'ab') as fh: fh.write(b'\0')       # another process touches the source meanwhile
    with pytest.raises(write.Refused): write.edit_file(f, edit, lambda ds: ds == ['layers differs'])
    assert open(f, 'rb').read().endswith(b'\0') and not os.path.exists(f + '.bak')
    assert [p for p in os.listdir(tmp_path) if p.startswith('.3dmballet')] == []


def test_census_loss_semantics():
    import collections
    a = collections.Counter({('10000019', '20008074'): 2, ('10000017', 'x'): 1})
    assert write.census_loss(a, collections.Counter({('10000019', '20008074'): 1, ('10000017', 'x'): 5})) == ['10000019/20008074: 2 -> 1']
    assert write.census_loss(a, collections.Counter({('10000019', '20008074'): 2, ('10000017', 'x'): 1, ('new', 'y'): 3})) == []


@pytest.mark.parametrize('f', [p for p in FILES if os.path.basename(p) not in KNOWN_LOSSY], ids=os.path.basename)
def test_census_no_loss_on_noedit_rewrite(f, tmp_path):
    m = R.File3dm.Read(f)
    if write.gate(m) or m.ArchiveVersion < 50: pytest.skip('gate/old format')
    o = str(tmp_path / 'o.3dm'); assert m.Write(o, m.ArchiveVersion)
    assert write.census_loss(write.census(f), write.census(o)) == []


def test_census_catches_known_lossy_example(tmp_path):
    f = os.path.join(D, 'V5-v5_example_file.3dm'); m = R.File3dm.Read(f)
    o = str(tmp_path / 'o.3dm'); m.Write(o, m.ArchiveVersion)
    assert write.census_loss(write.census(f), write.census(o)) != []


def _inject_unknown_record(src, dst, table=0x10000010, code=0x20001234, payload=b'ABCD'):
    """insert an unknown record (no CRC flag) just before the end-of-table chunk of `table`; fix the table length"""
    import struct
    b = bytearray(open(src, 'rb').read()); o = 32
    while o + 12 <= len(b):
        t, l = struct.unpack_from('<Iq', b, o)
        if t == table:
            inner = o + 12; end = inner + l; p = inner; last = None
            while p + 12 <= end:
                t2, l2 = struct.unpack_from('<Iq', b, p); last = p; p += 12 + l2
            assert struct.unpack_from('<I', b, last)[0] == 0xffffffff
            rec = struct.pack('<Iq', code, len(payload)) + payload
            b[last:last] = rec; struct.pack_into('<q', b, o + 4, l + len(rec))
            open(dst, 'wb').write(b); return True
        o += 12 + l
    return False


def test_unknown_record_in_known_table_is_refused_not_silently_dropped(tmp_path):
    f = str(tmp_path / 'a.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f)
    assert _inject_unknown_record(os.path.join(D, 'V7-v7_my_brep.3dm'), f)
    before = open(f, 'rb').read(); m = R.File3dm.Read(f)
    if m is None: pytest.skip('library rejects the crafted file (also safe)')
    lay = m.Layers[0].Name
    with pytest.raises(write.Refused): write.rename_layer(f, lay, lay + '_x')
    assert open(f, 'rb').read() == before and not os.path.exists(f + '.bak')


def test_trailing_bytes_after_eof_chunk_refused(tmp_path):
    f = str(tmp_path / 'a.3dm'); b = open(os.path.join(D, 'V7-v7_my_brep.3dm'), 'rb').read()
    open(f, 'wb').write(b + b'JUNKJUNK' * 4); before = open(f, 'rb').read(); lay = R.File3dm.Read(f).Layers[0].Name
    with pytest.raises(write.Refused): write.rename_layer(f, lay, lay + '_x')
    assert open(f, 'rb').read() == before and not os.path.exists(f + '.bak')


def test_unknown_record_in_object_table_refused(tmp_path):
    f = str(tmp_path / 'a.3dm'); assert _inject_unknown_record(os.path.join(D, 'V7-v7_my_brep.3dm'), f, table=0x10000013)
    before = open(f, 'rb').read(); lay = R.File3dm.Read(f).Layers[0].Name
    with pytest.raises(write.Refused): write.rename_layer(f, lay, lay + '_x')
    assert open(f, 'rb').read() == before


def test_lock_blocks_concurrent_save_and_is_released(tmp_path):
    f = str(tmp_path / 'a.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f); before = open(f, 'rb').read(); lay = R.File3dm.Read(f).Layers[0].Name
    open(f + '.3dmballet.lock', 'w').write(str(os.getpid()))
    with pytest.raises(write.Refused, match='in progress'): write.rename_layer(f, lay, lay + '_x')
    assert open(f, 'rb').read() == before
    os.utime(f + '.3dmballet.lock', (1, 1))            # stale lock (killed save) is broken
    write.rename_layer(f, lay, lay + '_x')
    assert not os.path.exists(f + '.3dmballet.lock') and R.File3dm.Read(f).Layers[0].Name == lay + '_x'


def test_lock_released_after_refusal(tmp_path):
    f = str(tmp_path / 'a.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f)
    with pytest.raises(write.Refused): write.rename_layer(f, 'no such layer', 'x')
    assert not os.path.exists(f + '.3dmballet.lock')


def test_parallel_processes_serialise(tmp_path):
    """8 processes rename the same layer to different names at once: file stays valid, equals exactly one of the names"""
    import subprocess, sys
    f = str(tmp_path / 'a.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f); lay = R.File3dm.Read(f).Layers[0].Name
    root = os.path.dirname(os.path.dirname(__file__))
    code = ('import sys\nsys.path[:0]=[%r,%r]\nfrom tm3dballet import write\n'
            'try: write.rename_layer(%r,%r,"n"+sys.argv[1]); print("ok")\nexcept write.Refused as e: print("refused")\n') % (root, os.path.join(root, '.deps'), f, lay)
    ps = [subprocess.Popen([sys.executable, '-I', '-c', code, str(i)], stdout=subprocess.PIPE) for i in range(8)]
    outs = [p.communicate(timeout=120)[0].decode().strip() for p in ps]
    assert outs.count('ok') == 1, outs
    m = R.File3dm.Read(f); assert m is not None and m.Layers[0].Name in ['n%d' % i for i in range(8)]
    assert not os.path.exists(f + '.3dmballet.lock')


@pytest.mark.parametrize('f', FILES, ids=os.path.basename)
def test_real_rename_accepted_or_refused_never_damaged(f, tmp_path):
    """real edit on every public sample: either saved correctly (name changed, object count and table census kept) or refused with bytes identical"""
    import hashlib
    t = str(tmp_path / 'a.3dm'); shutil.copy(f, t); h = hashlib.sha256(open(t, 'rb').read()).hexdigest()
    m = R.File3dm.Read(t)
    if m is None: pytest.skip('unreadable')
    lay = m.Layers[0].Name; n0 = len(m.Objects)
    try: write.rename_layer(t, lay, lay + '_r')
    except write.Refused:
        assert hashlib.sha256(open(t, 'rb').read()).hexdigest() == h; return
    n = R.File3dm.Read(t)
    assert n.Layers[0].Name == lay + '_r' and len(n.Objects) == n0
    if m.ArchiveVersion >= 50: assert write.census_loss(write.census(f), write.census(t)) == []


def _A(m): return m.Objects[0].Attributes

MUTATIONS = {
    'obj name': lambda m: setattr(_A(m), 'Name', 'zzz'),
    'obj layer': lambda m: setattr(_A(m), 'LayerIndex', _A(m).LayerIndex + 1),
    'obj color': lambda m: setattr(_A(m), 'ObjectColor', (1, 2, 3, 255)),
    'obj visible': lambda m: setattr(_A(m), 'Visible', not _A(m).Visible),
    'obj material idx': lambda m: setattr(_A(m), 'MaterialIndex', _A(m).MaterialIndex + 1),
    'obj linetype idx': lambda m: setattr(_A(m), 'LinetypeIndex', _A(m).LinetypeIndex + 1),
    'obj plotweight': lambda m: setattr(_A(m), 'PlotWeight', _A(m).PlotWeight + 0.5),
    'obj userstring': lambda m: _A(m).SetUserString('k', 'v'),
    'obj shadows': lambda m: setattr(_A(m), 'CastsShadows', not _A(m).CastsShadows),
    'obj url': lambda m: setattr(_A(m), 'Url', 'http://x'),
    'obj geom move': lambda m: m.Objects[0].Geometry.Transform(R.Transform.Translation(1, 0, 0)),
    'layer name': lambda m: setattr(m.Layers[0], 'Name', 'q'),
    'layer color': lambda m: setattr(m.Layers[0], 'Color', (9, 9, 9, 255)),
    'layer visible': lambda m: setattr(m.Layers[0], 'Visible', not m.Layers[0].Visible),
    'layer locked': lambda m: setattr(m.Layers[0], 'Locked', not m.Layers[0].Locked),
    'layer plotweight': lambda m: setattr(m.Layers[0], 'PlotWeight', m.Layers[0].PlotWeight + 1),
    'layer userstring': lambda m: m.Layers[0].SetUserString('a', 'b'),
    'units': lambda m: setattr(m.Settings, 'ModelUnitSystem', R.UnitSystem.Feet if m.Settings.ModelUnitSystem != R.UnitSystem.Feet else R.UnitSystem.Meters),
    'abs tol': lambda m: setattr(m.Settings, 'ModelAbsoluteTolerance', m.Settings.ModelAbsoluteTolerance * 2),
    'base point': lambda m: setattr(m.Settings, 'ModelBasePoint', R.Point3d(5, 5, 5)),
    'app name': lambda m: setattr(m, 'ApplicationName', 'x'),
}

@pytest.mark.parametrize('name', sorted(MUTATIONS))
def test_snapshot_not_blind_to(name):
    """every listed in-memory change must show up in diff(); a blind spot here is a way a bad save could pass the gate"""
    hit = False
    for f in ('V7-v7_my_brep.3dm', 'V7-v7_my_mesh_with_material.3dm'):
        m = R.File3dm.Read(os.path.join(D, f)); a = write.snapshot(m)
        MUTATIONS[name](m)
        if write.diff(a, write.snapshot(m)): hit = True; break
    assert hit


def test_doc_user_text_count_is_read():
    m = R.File3dm.Read(os.path.join(D, 'V7-v7_my_brep.3dm'))
    assert write._doc_strings(m) != ['unreadable']


@pytest.mark.parametrize('f', [p for p in FILES if os.path.basename(p) not in KNOWN_LOSSY], ids=os.path.basename)
def test_stable_settings_payloads_unchanged_by_rewrite(f, tmp_path):
    m = R.File3dm.Read(f)
    if write.gate(m) or m.ArchiveVersion < 50: pytest.skip('gate/old format')
    o = str(tmp_path / 'o.3dm'); assert m.Write(o, m.ArchiveVersion)
    assert write.stable_payloads(f) == write.stable_payloads(o)


def test_settings_payload_change_without_settings_edit_is_refused(tmp_path, monkeypatch):
    f = str(tmp_path / 'a.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f); before = open(f, 'rb').read(); lay = R.File3dm.Read(f).Layers[0].Name
    real = write.stable_payloads; n = {'i': 0}
    def fake(p):
        d = real(p); n['i'] += 1
        if n['i'] == 2: d = {k: ['00'] for k in d}      # output side differs
        return d
    monkeypatch.setattr(write, 'stable_payloads', fake)
    with pytest.raises(write.Refused, match='settings records'): write.rename_layer(f, lay, lay + '_x')
    assert open(f, 'rb').read() == before


def test_no_unreadable_placeholders_in_snapshots():
    """a '?' or 'unreadable' placeholder means a field compares nothing (this hid the DocumentUserTextCount bug)"""
    bad = []
    def walk(x, p):
        if isinstance(x, dict): [walk(v, p + '/' + k) for k, v in x.items() if p != '/objects' or True]
        elif isinstance(x, (list, tuple)): [walk(v, p + '[]') for v in x]
        elif x in ('?', 'unreadable'): bad.append(p)
    for f in FILES:
        m = R.File3dm.Read(f)
        if m is None or write.gate(m): continue
        walk(write.snapshot(m), '')
    assert sorted(set(bad)) == [], sorted(set(bad))


@pytest.mark.parametrize('f', FILES, ids=os.path.basename)
def test_object_census_noedit_rewrite_never_loses_chunks_in_accepted_files(f, tmp_path):
    """sweep: files the gate accepts keep every chunk typecode inside object records after a rewrite"""
    m = R.File3dm.Read(f)
    if m is None or write.gate(m) or m.ArchiveVersion < 50: pytest.skip('n/a')
    out = str(tmp_path / 'o.3dm'); m.Write(out, m.ArchiveVersion)
    assert write.census_loss(write.object_census(f), write.object_census(out)) == [] or os.path.basename(f) in KNOWN_LOSSY


def test_object_census_detects_dropped_chunk(tmp_path):
    from collections import Counter
    a = Counter({('obj', '00027ffa'): 2, ('obj', '40008001'): 1}); b = Counter({('obj', '00027ffa'): 2})
    assert write.census_loss(a, b) == ['obj/40008001: 1 -> 0']


def _inject_object_chunk(src, dst):
    """insert an unknown 4-byte chunk (as a userdata-like extra) at the end of the first object record, fixing parent lengths"""
    import struct
    b = bytearray(open(src, 'rb').read()); o = 32
    while o + 12 <= len(b):
        t, l = struct.unpack_from('<Iq', b, o)
        if t == 0x10000013:
            r = o + 12; t2, l2 = struct.unpack_from('<Iq', b, r)
            extra = struct.pack('<Iq', 0x40008abc, 4) + b'\1\2\3\4'
            end = r + 12 + l2 - 4          # record payload ends with a 4-byte CRC (typecode bit 0x8000)
            b[end:end] = extra
            import zlib
            crc = zlib.crc32(bytes(b[r + 12:end + len(extra)])) & 0xffffffff
            b[end + len(extra):end + len(extra) + 4] = struct.pack('<I', crc)
            struct.pack_into('<q', b, r + 4, l2 + len(extra)); struct.pack_into('<q', b, o + 4, l + len(extra))
            open(dst, 'wb').write(b); return
        o += 12 + l
    raise AssertionError('no object table')


def test_extra_chunk_in_object_record_is_never_silently_dropped(tmp_path):
    src = next(q for q in FILES if os.path.basename(q).startswith('V8-'))
    f = str(tmp_path / 'x.3dm'); _inject_object_chunk(src, f)
    assert write.object_census(f)[('obj', '40008abc')] == 1
    m = R.File3dm.Read(f); before = open(f, 'rb').read()
    if m is None: pytest.skip('library refuses the file itself (also safe)')
    lay = m.Layers[0].Name
    try: write.rename_layer(f, lay, lay + '_x')
    except write.Refused: assert open(f, 'rb').read() == before and not os.path.exists(f + '.bak'); return
    assert write.object_census(f)[('obj', '40008abc')] == 1, 'accepted save dropped the extra chunk'


PREVIEW_CHANGED = {'rh_AllMeshModifiers.3dm', 'rh_RenderContent.3dm', 'rh_blocks.3dm', 'rh_groups.3dm', 'rh_light.3dm', 'rh_meshWithTexture.3dm',
                   'rh_object_UserStrings.3dm', 'rh_subd.3dm', 'rh_subdBox.3dm', 'rh_textEntities_r8.3dm', 'rh_unassignedmaterials.3dm'}

def _preview(path):
    b = open(path, 'rb').read(); r = write._find_record(b, 0x10000014, write.PREVIEW)
    return None if r is None else b[r[1] + 12:r[1] + 12 + r[2]]

@pytest.mark.parametrize('name', sorted(PREVIEW_CHANGED))
def test_saved_file_keeps_original_preview_image_and_valid_length(name, tmp_path):
    """the library rewrites the thumbnail (3 MB -> a few KB); the gate must carry the original bytes over"""
    import struct
    f = str(tmp_path / name); shutil.copy(next(q for q in FILES if os.path.basename(q) == name), f)
    pv = _preview(f); lay = R.File3dm.Read(f).Layers[0].Name
    try: write.rename_layer(f, lay, lay + '_x')
    except write.Refused: pytest.skip('refused (also safe)')
    assert _preview(f) == pv
    b = open(f, 'rb').read(); assert struct.unpack_from('<q', b, len(b) - 8)[0] == len(b)
    assert R.File3dm.Read(f).Layers[0].Name == lay + '_x'


@pytest.mark.parametrize('f', FILES, ids=os.path.basename)
def test_notes_survive_noedit_rewrite_or_are_refused(f, tmp_path):
    m = R.File3dm.Read(f)
    if m is None or write.gate(m) or m.ArchiveVersion < 50: pytest.skip('n/a')
    n0 = write.notes_of(f)
    if n0 is None: pytest.skip('no notes record')
    assert n0 != 'unparsed'
    out = str(tmp_path / 'o.3dm'); m.Write(out, m.ArchiveVersion)
    assert write.notes_of(out) == n0 or os.path.basename(f) in KNOWN_LOSSY


def test_notes_change_is_refused(tmp_path, monkeypatch):
    src = next(q for q in FILES if os.path.basename(q) == 'V5-v5_my_curves.3dm'); f = str(tmp_path / 'a.3dm'); shutil.copy(src, f); before = open(f, 'rb').read()
    real = write.notes_of
    monkeypatch.setattr(write, 'notes_of', lambda p: real(p) if p == f else (1, 'other', 0, (0, 0, 0, 0)))
    lay = R.File3dm.Read(f).Layers[0].Name
    with pytest.raises(write.Refused, match='notes'): write.rename_layer(f, lay, lay + '_x')
    assert open(f, 'rb').read() == before


@pytest.mark.parametrize('f', FILES, ids=os.path.basename)
def test_user_records_survive_noedit_rewrite(f, tmp_path):
    m = R.File3dm.Read(f)
    if m is None or write.gate(m) or m.ArchiveVersion < 50: pytest.skip('n/a')
    out = str(tmp_path / 'o.3dm'); m.Write(out, m.ArchiveVersion)
    assert write.user_record_loss(write.user_records(f), write.user_records(out)) == [] or os.path.basename(f) in KNOWN_LOSSY


def test_foreign_plugin_user_record_change_is_refused(tmp_path, monkeypatch):
    src = next(q for q in FILES if os.path.basename(q) == 'V5-v5_my_curves.3dm'); f = str(tmp_path / 'a.3dm'); shutil.copy(src, f); before = open(f, 'rb').read()
    real = write.user_records
    monkeypatch.setattr(write, 'user_records', lambda p: [('11' * 16, b'x' * 50)] if p == f else real(p))
    lay = R.File3dm.Read(f).Layers[0].Name
    with pytest.raises(write.Refused, match='user record|re-encoded or dropped records'): write.rename_layer(f, lay, lay + '_x')
    assert open(f, 'rb').read() == before


def _t19(path):
    r = write._table_records(open(path, 'rb').read(), 0x10000019)
    return [] if r is None else sorted(p for _, _, _, p in r[2])

FONT_CHANGED = ['V5-v5_extrusions.3dm', 'V5-v5_my_brep.3dm', 'V5-v5_my_curves.3dm', 'V5-v5_my_points.3dm']

@pytest.mark.parametrize('name', FONT_CHANGED)
def test_table_19_records_keep_source_bytes_after_save(name, tmp_path):
    """the library rewrites a text-style/font record ('Default' -> 'ArialMT'); the guarded save puts the source record back"""
    import struct
    f = str(tmp_path / name); shutil.copy(next(q for q in FILES if os.path.basename(q) == name), f)
    src = _t19(f); assert src
    m = R.File3dm.Read(f); raw = str(tmp_path / 'raw.3dm'); m.Write(raw, m.ArchiveVersion)
    if _t19(raw) == src: pytest.skip('library does not alter this file')
    lay = m.Layers[0].Name
    try: write.rename_layer(f, lay, lay + '_x')
    except write.Refused: pytest.skip('refused (also safe)')
    assert _t19(f) == src
    b = open(f, 'rb').read(); assert struct.unpack_from('<q', b, len(b) - 8)[0] == len(b)
    assert R.File3dm.Read(f).Layers[0].Name == lay + '_x'


def _settings(path):
    r = write._table_records(open(path, 'rb').read(), 0x10000015)
    return None if r is None else sorted((t, p) for _, _, t, p in r[2])

@pytest.mark.parametrize('f', FILES, ids=os.path.basename)
def test_settings_table_bytes_identical_after_layer_rename(f, tmp_path):
    """settings the user did not edit are put back byte for byte (the library re-emits them with a bumped minor version / extra fields)"""
    m = R.File3dm.Read(f)
    if m is None or write.gate(m) or m.ArchiveVersion < 50: pytest.skip('n/a')
    g = str(tmp_path / 'a.3dm'); shutil.copy(f, g); s0 = _settings(g); lay = m.Layers[0].Name
    try: write.rename_layer(g, lay, lay + '_x')
    except write.Refused: pytest.skip('refused (also safe)')
    s1 = _settings(g)
    assert s1 == s0 or [t for (t, p), (t2, p2) in zip(s0, s1) if p != p2] == [], 'settings records differ'
    assert R.File3dm.Read(g).Layers[0].Name == lay + '_x'


def _objs(path):
    r = write._table_records(open(path, 'rb').read(), 0x10000013)
    return None if r is None else [p for _, _, t, p in r[2]]

@pytest.mark.parametrize('f', FILES, ids=os.path.basename)
def test_object_records_byte_identical_after_layer_rename(f, tmp_path):
    """object records the user did not edit keep the source bytes (the library re-encodes ~70 percent of them)"""
    m = R.File3dm.Read(f)
    if m is None or write.gate(m) or m.ArchiveVersion < 50: pytest.skip('n/a')
    g = str(tmp_path / 'a.3dm'); shutil.copy(f, g); o0 = _objs(g); lay = m.Layers[0].Name
    try: write.rename_layer(g, lay, lay + '_x')
    except write.Refused: pytest.skip('refused (also safe)')
    assert _objs(g) == o0, 'object records differ from source'
    assert R.File3dm.Read(g).Layers[0].Name == lay + '_x'


def _tbl(path, t):
    r = write._table_records(open(path, 'rb').read(), t)
    return None if r is None else [p for _, _, _, p in r[2]]

@pytest.mark.parametrize('f', FILES, ids=os.path.basename)
def test_user_table_source_records_kept_after_layer_rename(f, tmp_path):
    """every plug-in user record present in the source is still present, byte for byte, after a save"""
    m = R.File3dm.Read(f)
    if m is None or write.gate(m) or m.ArchiveVersion < 50: pytest.skip('n/a')
    g = str(tmp_path / 'a.3dm'); shutil.copy(f, g); u0 = _tbl(g, 0x10000020) or []; lay = m.Layers[0].Name
    try: write.rename_layer(g, lay, lay + '_x')
    except write.Refused: pytest.skip('refused (also safe)')
    u1 = _tbl(g, 0x10000020) or []
    assert all(p in u1 for p in u0), 'source user record changed'


@pytest.mark.parametrize('f', FILES, ids=os.path.basename)
def test_render_content_table_identical_after_layer_rename(f, tmp_path):
    """table 0x10000017 is neither added nor re-serialised by the save"""
    m = R.File3dm.Read(f)
    if m is None or write.gate(m) or m.ArchiveVersion < 50: pytest.skip('n/a')
    g = str(tmp_path / 'a.3dm'); shutil.copy(f, g); u0 = _tbl(g, 0x10000017); lay = m.Layers[0].Name
    try: write.rename_layer(g, lay, lay + '_x')
    except write.Refused: pytest.skip('refused (also safe)')
    assert _tbl(g, 0x10000017) == u0
    assert R.File3dm.Read(g).Layers[0].Name == lay + '_x'


@pytest.mark.parametrize('f', FILES, ids=os.path.basename)
def test_material_light_and_misc_tables_identical_after_layer_rename(f, tmp_path):
    """tables no layer edit touches (material, light, 0x10000023/25/26) keep their source records byte for byte"""
    m = R.File3dm.Read(f)
    if m is None or write.gate(m) or m.ArchiveVersion < 50: pytest.skip('n/a')
    g = str(tmp_path / 'a.3dm'); shutil.copy(f, g)
    before = {t: _tbl(g, t) for t in write.POSITIONAL_TABLES}; lay = m.Layers[0].Name
    try: write.rename_layer(g, lay, lay + '_x')
    except write.Refused: pytest.skip('refused (also safe)')
    assert {t: _tbl(g, t) for t in write.POSITIONAL_TABLES} == before
    assert R.File3dm.Read(g).Layers[0].Name == lay + '_x'


@pytest.mark.parametrize('f', FILES, ids=os.path.basename)
def test_untouched_layer_records_identical_after_layer_rename(f, tmp_path):
    """only the renamed layer's record may differ; every other layer record keeps the source bytes"""
    m = R.File3dm.Read(f)
    if m is None or write.gate(m) or m.ArchiveVersion < 50: pytest.skip('n/a')
    g = str(tmp_path / 'a.3dm'); shutil.copy(f, g); a = _tbl(g, 0x10000011); lay = m.Layers[0].Name
    try: write.rename_layer(g, lay, lay + '_x')
    except write.Refused: pytest.skip('refused (also safe)')
    b = _tbl(g, 0x10000011)
    assert len(a) == len(b) and sum(x != y for x, y in zip(a, b)) <= 1
    assert R.File3dm.Read(g).Layers[0].Name == lay + '_x'


@pytest.mark.parametrize('f', FILES, ids=os.path.basename)
def test_notes_record_bytes_identical_after_layer_rename(f, tmp_path):
    """document notes record (0x20008022) keeps the source bytes; the library re-encodes it with a bumped minor version"""
    m = R.File3dm.Read(f)
    if m is None or write.gate(m) or m.ArchiveVersion < 50: pytest.skip('n/a')
    g = str(tmp_path / 'a.3dm')
    shutil.copy(f, g)
    def notes(p):
        r = write._table_records(open(p, 'rb').read(), 0x10000014)
        return [x[3] for x in r[2] if x[2] == 0x20008022]
    n0 = notes(g); lay = m.Layers[0].Name
    try: write.rename_layer(g, lay, lay + '_x')
    except write.Refused: pytest.skip('refused (also safe)')
    assert notes(g) == n0


@pytest.mark.parametrize('f', FILES, ids=os.path.basename)
def test_header_start_chunk_and_table_order_after_layer_rename(f, tmp_path):
    """32-byte header and start chunk keep the source bytes; the top-level chunk typecode sequence is unchanged (no extra render-content tables)"""
    import struct
    m = R.File3dm.Read(f)
    if m is None or write.gate(m) or m.ArchiveVersion < 50: pytest.skip('n/a')
    g = str(tmp_path / 'a.3dm'); shutil.copy(f, g); lay = m.Layers[0].Name
    def seq(p):
        b = open(p, 'rb').read(); o = 32; out = []
        while o + 12 <= len(b):
            t, l = struct.unpack_from('<Iq', b, o); out.append((t, b[o + 12:o + 12 + l] if t == 1 else None)); o += 12 + l
            if t == 0x7fff: break
        return b[:32], out
    h0, s0 = seq(g)
    try: write.rename_layer(g, lay, lay + '_x')
    except write.Refused: pytest.skip('refused (also safe)')
    h1, s1 = seq(g)
    assert h0 == h1 and s0[0] == s1[0] and [t for t, _ in s0] == [t for t, _ in s1]


@pytest.mark.parametrize('bad', ['', '  ', 'a\x00b', 'a\nb', 'a::b', 'x' * 1001, ' pad'])
def test_rename_layer_refuses_invalid_names(bad, tmp_path):
    """names Rhino would truncate, repair or reject are refused before any write; the file is untouched"""
    f = [x for x in FILES if 'V7-v7_my_cur' in x]
    if not f: pytest.skip('sample missing')
    g = str(tmp_path / 'a.3dm'); shutil.copy(f[0], g); b0 = open(g, 'rb').read(); lay = R.File3dm.Read(g).Layers[0].Name
    with pytest.raises(write.Refused): write.rename_layer(g, lay, bad)
    assert open(g, 'rb').read() == b0


def test_rename_layer_refuses_sibling_duplicate(tmp_path):
    f = [x for x in FILES if 'V7-v7_my_cur' in x]
    if not f: pytest.skip('sample missing')
    g = str(tmp_path / 'a.3dm'); shutil.copy(f[0], g); b0 = open(g, 'rb').read(); m = R.File3dm.Read(g)
    if len(m.Layers) < 2 or str(m.Layers[0].ParentLayerId) != str(m.Layers[1].ParentLayerId): pytest.skip('layers not siblings')
    with pytest.raises(write.Refused): write.rename_layer(g, m.Layers[0].Name, m.Layers[1].Name)
    assert open(g, 'rb').read() == b0


def test_rename_layer_unicode_name_roundtrips(tmp_path):
    f = [x for x in FILES if 'V7-v7_my_cur' in x]
    if not f: pytest.skip('sample missing')
    g = str(tmp_path / 'a.3dm'); shutil.copy(f[0], g); lay = R.File3dm.Read(g).Layers[0].Name
    write.rename_layer(g, lay, 'Ünï☃ 层 😀')
    assert R.File3dm.Read(g).Layers[0].Name == 'Ünï☃ 层 😀'


def _nested_file(path):
    import uuid
    m = R.File3dm()
    def lay(name, parent=None):
        l = R.Layer(); l.Name = name; l.Id = uuid.uuid4()
        if parent is not None: l.ParentLayerId = parent.Id
        m.Layers.Add(l); return m.Layers[len(m.Layers) - 1]
    a = lay('Arch'); b = lay('Walls', a); lay('Doors', b); c = lay('Other'); lay('Doors', c)
    m.Objects.AddPoint(R.Point3d(1, 2, 3), R.ObjectAttributes())
    m.Write(path, 8)

@pytest.mark.parametrize('old,new', [('Arch', 'Arch2'), ('Walls', 'Walls2'), ('Other', 'Other2')])
def test_rename_nested_layer_keeps_ids_and_parents(old, new, tmp_path):
    """synthetic nested layers: ids and parent links are unchanged, full paths follow the rename, untouched layer records keep their bytes"""
    g = str(tmp_path / 'n.3dm'); _nested_file(g)
    r0 = R.File3dm.Read(g); sig0 = [(str(l.Id), str(l.ParentLayerId)) for l in r0.Layers]
    write.rename_layer(g, old, new)
    r1 = R.File3dm.Read(g)
    assert [(str(l.Id), str(l.ParentLayerId)) for l in r1.Layers] == sig0
    assert [l.Name for l in r1.Layers if l.Name == new] == [new]
    assert not any(l.FullPath.split('::')[i:i + 1] == [old] for l in r1.Layers for i in range(len(l.FullPath.split('::'))))


def test_rename_ambiguous_nested_name_refused(tmp_path):
    """'Doors' exists under two parents: renaming by bare name is ambiguous and must be refused, file untouched"""
    g = str(tmp_path / 'n.3dm'); _nested_file(g); b0 = open(g, 'rb').read()
    with pytest.raises(write.Refused): write.rename_layer(g, 'Doors', 'Doors2')
    assert open(g, 'rb').read() == b0


def test_rename_layer_preserves_layer_attributes(tmp_path):
    """user strings, plot weight, colour, IGES level and expanded flag of the renamed layer survive the rename"""
    import uuid
    m = R.File3dm(); l = R.Layer(); l.Name = 'A'; l.Id = uuid.uuid4(); l.SetUserString('k', 'vü')
    l.PlotWeight = 0.35; l.Color = (10, 20, 30, 255); l.IgesLevel = 7; l.Expanded = False
    m.Layers.Add(l); m.Objects.AddPoint(R.Point3d(1, 2, 3), R.ObjectAttributes())
    g = str(tmp_path / 'n.3dm'); m.Write(g, 8)
    sig = lambda p: (dict(R.File3dm.Read(p).Layers[0].GetUserStrings()), R.File3dm.Read(p).Layers[0].PlotWeight, tuple(R.File3dm.Read(p).Layers[0].Color),
                     R.File3dm.Read(p).Layers[0].IgesLevel, R.File3dm.Read(p).Layers[0].Expanded, str(R.File3dm.Read(p).Layers[0].Id))
    s0 = sig(g); write.rename_layer(g, 'A', 'B')
    assert sig(g) == s0 and R.File3dm.Read(g).Layers[0].Name == 'B'


@pytest.mark.parametrize('step', ['restore_start', 'restore_preview', 'restore_records', 'drop_added_table', 'restore_objects'])
def test_process_killed_during_restore_step_leaves_original_identical(step, tmp_path):
    """hard kill inside each post-write restore step (works on the temp file only): original byte-identical, still loadable"""
    import subprocess, sys, textwrap
    f = str(tmp_path / 'a.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f); before = open(f, 'rb').read()
    root = os.path.dirname(os.path.dirname(__file__)); lay = R.File3dm.Read(f).Layers[0].Name
    code = textwrap.dedent('''
        import sys, os
        sys.path[:0] = [%r, %r]
        from tm3dballet import write
        def die(*a, **k): os._exit(9)
        setattr(write, %r, die)
        write.rename_layer(%r, %r, 'zzz')
    ''') % (root, os.path.join(root, '.deps'), step, f, lay)
    r = subprocess.run([sys.executable, '-I', '-c', code], timeout=120)
    assert r.returncode == 9
    assert open(f, 'rb').read() == before
    assert R.File3dm.Read(f).Layers[0].Name == lay


def test_four_processes_renaming_same_file_at_once(tmp_path):
    """real race: 4 processes rename the same layer to different names; the file ends up valid with exactly one of the new names,
    every loser is refused (lock or missing old name), no lock file remains"""
    import subprocess, sys, textwrap
    f = str(tmp_path / 'a.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f)
    root = os.path.dirname(os.path.dirname(__file__)); lay = R.File3dm.Read(f).Layers[0].Name
    code = textwrap.dedent('''
        import sys
        sys.path[:0] = [%r, %r]
        from tm3dballet import write
        try: write.rename_layer(%r, %r, sys.argv[1]); print('OK')
        except write.Refused as e: print('REFUSED')
    ''') % (root, os.path.join(root, '.deps'), f, lay)
    ps = [subprocess.Popen([sys.executable, '-I', '-c', code, 'name%d' % i], stdout=subprocess.PIPE, text=True) for i in range(4)]
    outs = [p.communicate(timeout=120)[0].strip() for p in ps]
    assert outs.count('OK') == 1 and outs.count('REFUSED') == 3, outs
    names = [l.Name for l in R.File3dm.Read(f).Layers]
    assert sum(n.startswith('name') for n in names) == 1 and lay not in names
    assert not os.path.exists(f + '.3dmballet.lock')


def test_write_timeout_scales_with_file_size(tmp_path):
    f = tmp_path / 'a.bin'; f.write_bytes(b'0' * 10)
    assert write.write_timeout(str(f)) == write.WRITE_TIMEOUT
    with open(f, 'r+b') as fh: fh.truncate(100 * 2**20)
    assert write.write_timeout(str(f)) == 1500
    with open(f, 'r+b') as fh: fh.truncate(1000 * 2**20)
    assert write.write_timeout(str(f)) == 3600


@pytest.mark.parametrize('limit', [1000, 20000, 60000])
def test_disk_full_simulated_by_file_size_limit_leaves_original_intact(limit, tmp_path):
    """RLIMIT_FSIZE makes every write past `limit` bytes fail (stand-in for a full disk): original byte-identical, loadable, no .bak/.lock left"""
    if os.name != 'posix': pytest.skip('posix only')
    import subprocess, sys, textwrap
    f = str(tmp_path / 'a.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f); before = open(f, 'rb').read()
    root = os.path.dirname(os.path.dirname(__file__)); lay = R.File3dm.Read(f).Layers[0].Name
    code = textwrap.dedent('''
        import sys, signal, resource
        sys.path[:0] = [%r, %r]
        signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
        from tm3dballet import write
        resource.setrlimit(resource.RLIMIT_FSIZE, (%d, %d))
        try: write.rename_layer(%r, %r, 'zzz'); print('SAVED')
        except write.Refused: print('REFUSED')
        except OSError: print('OSERROR')
    ''') % (root, os.path.join(root, '.deps'), limit, limit, f, lay)
    r = subprocess.run([sys.executable, '-I', '-c', code], capture_output=True, text=True, timeout=120)
    out = r.stdout.strip()
    assert out in ('REFUSED', 'OSERROR', 'SAVED'), (out, r.stderr[-300:])
    if len(before) > limit: assert out != 'SAVED'
    if out != 'SAVED': assert open(f, 'rb').read() == before and R.File3dm.Read(f).Layers[0].Name == lay
    assert not os.path.exists(f + '.3dmballet.lock')
    assert not [x for x in os.listdir(tmp_path) if x.startswith('.3dmballet-')], os.listdir(tmp_path)


@pytest.mark.parametrize('cut', [1, 8, 20, 100, 5000])
def test_truncated_source_is_refused_untouched(cut, tmp_path):
    """a source whose tail was cut off (partial copy, full disk when it was made) is never 'repaired' by a save"""
    f = str(tmp_path / 'a.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f)
    data = open(f, 'rb').read(); lay = R.File3dm.Read(f).Layers[0].Name
    open(f, 'wb').write(data[:-cut]); before = open(f, 'rb').read()
    with pytest.raises(write.Refused): write.rename_layer(f, lay, lay + '_x')
    assert open(f, 'rb').read() == before and not os.path.exists(f + '.bak')


def test_garbage_and_empty_sources_refused(tmp_path):
    for name, data in (('empty.3dm', b''), ('junk.3dm', b'not a 3dm file' * 100), ('hdr.3dm', b'3D Geometry File Format        8' + b'\0' * 40)):
        f = str(tmp_path / name); open(f, 'wb').write(data)
        with pytest.raises(write.Refused): write.rename_layer(f, 'x', 'y')
        assert open(f, 'rb').read() == data


def test_readonly_source_file_refused_or_original_intact(tmp_path):
    """chmod 444 source in a writable directory: replacing it would silently override the user's read-only flag"""
    if os.name != 'posix' or os.geteuid() == 0: pytest.skip('needs posix non-root')
    f = str(tmp_path / 'a.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f); os.chmod(f, 0o444)
    before = open(f, 'rb').read(); lay = R.File3dm.Read(f).Layers[0].Name
    try:
        with pytest.raises(write.Refused, match='read-only'): write.rename_layer(f, lay, lay + '_x')
        assert open(f, 'rb').read() == before and os.stat(f).st_mode & 0o777 == 0o444
    finally: os.chmod(f, 0o644)


def test_symlinked_source_edits_target_and_keeps_link(tmp_path):
    """saving through a symlink must not replace the link by a regular file (the real file would be left stale, the link silently detached)"""
    if os.name != 'posix': pytest.skip('symlinks')
    real = tmp_path / 'real'; real.mkdir(); t = str(real / 'a.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), t)
    link = str(tmp_path / 'link.3dm'); os.symlink(t, link); lay = R.File3dm.Read(t).Layers[0].Name
    try: write.rename_layer(link, lay, lay + '_x')
    except write.Refused: return   # refusing is also safe
    assert os.path.islink(link), 'link was replaced by a regular file'
    assert R.File3dm.Read(t).Layers[0].Name == lay + '_x'


@pytest.mark.parametrize('name', ['ünï cödé ☃ 层 file.3dm', 'with  double  spaces.3dm', 'a' * 240 + '.3dm', 'b' * 251 + '.3dm'])
def test_unusual_file_names_save_or_refuse_cleanly(name, tmp_path):
    """names that leave no room for the .bak/.lock/.tmp suffixes must be refused (not crash half way); others save, with backup"""
    f = str(tmp_path / name)
    try: shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f)
    except OSError: pytest.skip('filesystem refuses the name')
    before = open(f, 'rb').read(); lay = R.File3dm.Read(f).Layers[0].Name
    try: write.rename_layer(f, lay, lay + '_x')
    except write.Refused: saved = False
    else: saved = True
    if saved:
        assert R.File3dm.Read(f).Layers[0].Name == lay + '_x' and open(f + '.bak', 'rb').read() == before
    else:
        assert open(f, 'rb').read() == before
    left = [x for x in os.listdir(tmp_path) if x.startswith('.3dmballet-') or x.endswith('.lock')]
    assert not left, left


def test_backup_chain_restores_original_byte_identical(tmp_path):
    """three consecutive saves keep .bak, .bak.1, .bak.2; the first backup is the untouched original"""
    f = str(tmp_path / 'a.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f); orig = open(f, 'rb').read(); lay = R.File3dm.Read(f).Layers[0].Name
    states = [orig]
    for i in range(3):
        write.rename_layer(f, lay + '_' * i if i else lay, lay + '_' * (i + 1)); states.append(open(f, 'rb').read())
    baks = sorted(x for x in os.listdir(tmp_path) if x.startswith('a.3dm.bak'))
    assert len(baks) == 3, baks
    contents = [open(str(tmp_path / b), 'rb').read() for b in baks]
    assert sorted(contents) == sorted(states[:3]) and orig in contents
    shutil.copy(str(tmp_path / 'a.3dm.bak'), str(tmp_path / 'restored.3dm'))
    assert open(str(tmp_path / 'restored.3dm'), 'rb').read() == orig


@pytest.mark.parametrize('name', ['fuzz43_zeroed_brep.3dm', 'fuzz34_zeroed_points.3dm'])
def test_fuzz_escape_regression_library_added_user_record_dropped(name, tmp_path):
    """fuzz found (zeroed 64 bytes in a public sample): the guarded save added a library plug-in user record the source never had.
    Output records must equal the source except the renamed layer, version marker and revision record."""
    import collections, struct
    f = str(tmp_path / name); shutil.copy(os.path.join(os.path.dirname(__file__), 'regress', name), f); src = f + '.orig'; shutil.copy(f, src)
    m = R.File3dm.Read(f); lay = m.Layers[0].Name
    try: write.rename_layer(f, lay, lay + '_z')
    except write.Refused: return
    def recs(path):
        b = open(path, 'rb').read(); c = collections.Counter(); o = 32; seen = collections.Counter()
        while o + 12 <= len(b):
            t, l = struct.unpack_from('<Iq', b, o)
            if t == 0x7fff or l < 0: break
            r = write._table_records(b, t, seen[t]); seen[t] += 1
            for x in (r[2] if r else []): c[(t, x[2], bytes(x[3]))] += 1
            o += 12 + l
        return c
    A, B = recs(src), recs(f); allowed = {(0x10000014, 0xa0000026), (0x10000014, 0x20008027), (0x10000011, 0x20008050)}
    assert not [k for k in (A - B) | (B - A) if (k[0], k[1]) not in allowed]


@pytest.mark.parametrize('f', FILES, ids=os.path.basename)
def test_clean_samples_pass_structure_walk(f):
    m = R.File3dm.Read(f)
    if m is None or m.ArchiveVersion < 50: pytest.skip('n/a')
    assert write.structure_problem(f) is None


def test_fuzz_escape_regression_reencoded_font_record_refused(tmp_path):
    """fuzz seed 2 case 94 (64 zero bytes inside the 0x20008074 record of table 0x10000019): the library re-encodes that record and the id-keyed
    restore cannot find it; the save must be refused, original untouched"""
    f = str(tmp_path / 'a.3dm'); shutil.copy(os.path.join(os.path.dirname(__file__), 'regress', 'fuzz_s2c94_zeroed_font_record.3dm'), f); b0 = open(f, 'rb').read()
    lay = R.File3dm.Read(f).Layers[0].Name
    try: write.rename_layer(f, lay, lay + '_z')
    except write.Refused: assert open(f, 'rb').read() == b0; return
    # since the library-added record is dropped the save may go through, but then every table the rename does not touch must be byte-identical
    import struct
    def tops(x):
        o = 32; r = {}
        while o + 12 <= len(x):
            t, l = struct.unpack_from('<Iq', x, o); r[t] = x[o + 12:o + 12 + l]
            if t == 0x7fff: break
            o += 12 + l
        return r
    A, B = tops(b0), tops(open(f, 'rb').read())
    assert set(A) == set(B)
    assert {t for t in A if A[t] != B[t]} <= {0x10000011, 0x10000014, 0x7fff}


def _dup_layer_source(dst):
    """V6 my_curves with its first layer record inserted a second time (same id), table and end-of-file lengths fixed up"""
    import struct
    b = open(os.path.join(os.path.dirname(__file__), 'data', 'V6-my_curves.3dm'), 'rb').read()
    o, l, recs = write._table_records(b, 0x10000011)
    r0 = recs[0]; ins = b[r0[0]:r0[0] + r0[1]]; end = recs[-1][0]
    nb = bytearray(b[:end] + ins + b[end:]); struct.pack_into('<q', nb, o + 4, l + len(ins)); struct.pack_into('<q', nb, len(nb) - 8, len(nb))
    open(dst, 'wb').write(nb)


def test_source_with_duplicate_layer_record_is_refused(tmp_path):
    """queue 93/88: a duplicate layer id in the source was silently renumbered by the library on save (accepted, original replaced). Must refuse."""
    f = str(tmp_path / 'a.3dm'); _dup_layer_source(f); before = open(f, 'rb').read()
    with pytest.raises(write.Refused, match='duplicate|distinct|renumbered'): write.rename_layer(f, 'line layer', 'zz')
    assert open(f, 'rb').read() == before
    assert not os.path.exists(f + '.bak')


def test_pre_v5_archives_always_refused_and_untouched(tmp_path):
    """queue 97: every public V1-V4 sample (53 files): rename must refuse (no writer for those layouts) and leave the bytes alone, no .bak"""
    n = 0
    for src in sorted(glob.glob(os.path.join(os.path.dirname(__file__), 'data', 'V[1-4]*.3dm'))):
        f = str(tmp_path / 'a.3dm'); shutil.copy(src, f); before = open(f, 'rb').read(); m = R.File3dm.Read(f)
        if m is None or not len(m.Layers): continue
        with pytest.raises(write.Refused): write.rename_layer(f, m.Layers[0].Name, m.Layers[0].Name + '_x')
        assert open(f, 'rb').read() == before and not os.path.exists(f + '.bak'); n += 1
    assert n >= 40


def test_rename_to_same_name_refused_with_clear_reason(tmp_path):
    f = str(tmp_path / 'a.3dm'); shutil.copy(os.path.join(os.path.dirname(__file__), 'data', 'V7-v7_my_curves.3dm'), f); b = open(f, 'rb').read()
    n = R.File3dm.Read(f).Layers[0].Name
    with pytest.raises(write.Refused, match='equals the old'): write.rename_layer(f, n, n)
    assert open(f, 'rb').read() == b and os.listdir(str(tmp_path)) == ['a.3dm']


def _dangling_parent_source(dst):
    """synthetic V7 file with layers A and B (B child of A), B's parent id patched to an unknown uuid.
    The layer record's outer chunk CRC (last 4 bytes of the 0x2fffc chunk) skips the nested 0x40008000 chunk (16 data bytes + 12 header)."""
    import struct, uuid, zlib
    m = R.File3dm(); a = R.Layer(); a.Name = 'A'; m.Layers.Add(a); b = R.Layer(); b.Name = 'B'; b.ParentLayerId = m.Layers[0].Id; m.Layers.Add(b)
    m.Write(dst, 7); d = bytearray(open(dst, 'rb').read()); pid = m.Layers[0].Id.bytes_le
    r = [r for r in write._table_records(bytes(d), 0x10000011)[2] if r[2] == 0x20008050][1]; p0 = r[0] + 12; p = bytearray(d[p0:p0 + len(r[3])])
    i = p.find(pid); assert i > 0
    p[i:i + 16] = uuid.uuid4().bytes_le
    inner = 160; assert struct.unpack_from('<I', p, inner)[0] == 0x40008000
    struct.pack_into('<I', p, len(p) - 20, zlib.crc32(bytes(p[56:inner] + p[inner + 28:len(p) - 20])))
    d[p0:p0 + len(p)] = p; open(dst, 'wb').write(d)


def test_source_with_dangling_layer_parent_keeps_child_record_bytes(tmp_path):
    """queue 93 rest: the library repairs a dangling parent id on load (parent becomes none); the save must not carry that silent repair into
    the untouched child layer: its record stays byte-identical to the source, only the renamed layer's record changes"""
    f = str(tmp_path / 'a.3dm'); _dangling_parent_source(f)
    assert R.File3dm.Read(f) is not None
    before = open(f, 'rb').read(); write.rename_layer(f, 'A', 'AA')
    ra = [r for r in write._table_records(before, 0x10000011)[2] if r[2] == 0x20008050]; rb = [r for r in write._table_records(open(f, 'rb').read(), 0x10000011)[2] if r[2] == 0x20008050]
    assert ra[1][3] == rb[1][3] and ra[0][3] != rb[0][3]


def test_source_with_layer_parent_cycle_refused_or_records_preserved(tmp_path):
    """queue 104: A.parent=B, B.parent=A (CRC-valid byte patch of the 0x2fffc chunk). The save may refuse (it does today) but must never
    leave the original damaged; if it ever saves, every untouched layer record must stay byte-identical."""
    import struct, zlib
    f = str(tmp_path / 'a.3dm'); m = R.File3dm(); a = R.Layer(); a.Name = 'A'; m.Layers.Add(a); b = R.Layer(); b.Name = 'B'; b.ParentLayerId = m.Layers[0].Id; m.Layers.Add(b)
    m.Write(f, 7); d = bytearray(open(f, 'rb').read()); ids = [l.Id for l in R.File3dm.Read(f).Layers]
    recs = [r for r in write._table_records(bytes(d), 0x10000011)[2] if r[2] == 0x20008050]
    off = recs[1][3].find(ids[0].bytes_le); p0 = recs[0][0] + 12; p = bytearray(d[p0:p0 + len(recs[0][3])]); p[off:off + 16] = ids[1].bytes_le
    inner = [i for i in range(56, len(p) - 12) if struct.unpack_from('<I', p, i)[0] == 0x40008000][0]
    struct.pack_into('<I', p, len(p) - 20, zlib.crc32(bytes(p[56:inner] + p[inner + 28:len(p) - 20])))
    d[p0:p0 + len(p)] = p; open(f, 'wb').write(d); before = bytes(d)
    try: write.rename_layer(f, 'B', 'BB')
    except write.Refused: assert open(f, 'rb').read() == before; return
    ra = [r for r in write._table_records(before, 0x10000011)[2] if r[2] == 0x20008050]; rb = [r for r in write._table_records(open(f, 'rb').read(), 0x10000011)[2] if r[2] == 0x20008050]
    assert ra[0][3] == rb[0][3]


def test_deep_layer_tree_rename_not_falsely_refused(tmp_path):
    """queue 105: the first layer-id gate counted a parent id appearing in its children's records as a duplicate and refused every nested file
    (and was quadratic with str() calls: 144 s for 2000 layers). 300 layers, chains of 20: rename must succeed, only the renamed record changes."""
    f = str(tmp_path / 'a.3dm'); m = R.File3dm(); prev = None
    for i in range(300):
        l = R.Layer(); l.Name = 'L%d' % i
        if prev is not None and i % 20: l.ParentLayerId = prev
        m.Layers.Add(l); prev = m.Layers[len(m.Layers) - 1].Id
    m.Write(f, 7); before = open(f, 'rb').read()
    assert write.rename_layer(f, 'L150', 'L150x') == ['layers differs']
    ra = [r[3] for r in write._table_records(before, 0x10000011)[2] if r[2] == 0x20008050]; rb = [r[3] for r in write._table_records(open(f, 'rb').read(), 0x10000011)[2] if r[2] == 0x20008050]
    assert len(ra) == len(rb) == 300 and sum(x != y for x, y in zip(ra, rb)) == 1


def test_rename_with_non_ascii_layer_names_keeps_other_layers(tmp_path):
    """UTF-16 names (umlaut, CJK, astral emoji) in other layers survive a rename unchanged; renamed layer takes the new unicode name"""
    f = str(tmp_path / 'u.3dm'); m = R.File3dm()
    names = ['Ünïcode Ebene', '壁 / 墙', 'Ωmega 😀', 'plain']
    for n in names:
        l = R.Layer(); l.Name = n; m.Layers.Add(l)
    assert m.Write(f, 7)
    write.rename_layer(f, names[0], 'Ebene ß')
    assert [l.Name for l in R.File3dm.Read(f).Layers] == ['Ebene ß'] + names[1:]
    write.rename_layer(f, names[2], 'x')
    assert [l.Name for l in R.File3dm.Read(f).Layers] == ['Ebene ß', names[1], 'x', 'plain']


def test_rename_long_and_colon_layer_names(tmp_path):
    """250-char names and single colons are accepted and leave other layers alone; '::' in a new name is refused (layer path separator) with the file unchanged"""
    f = str(tmp_path / 'c.3dm'); m = R.File3dm()
    names = ['a' * 200, 'A::B', 'x:y', 'plain']
    for n in names:
        l = R.Layer(); l.Name = n; m.Layers.Add(l)
    assert m.Write(f, 7)
    write.rename_layer(f, names[0], 'b' * 250)
    assert [l.Name for l in R.File3dm.Read(f).Layers] == ['b' * 250] + names[1:]
    before = open(f, 'rb').read()
    with pytest.raises(write.Refused): write.rename_layer(f, names[1], 'C::D')
    assert open(f, 'rb').read() == before
    write.rename_layer(f, names[3], 'q:r')
    assert [l.Name for l in R.File3dm.Read(f).Layers] == ['b' * 250, 'A::B', 'x:y', 'q:r']


def test_source_with_gaps_in_layer_indices_keeps_other_records(tmp_path):
    """queue 108: layers A,B,C whose record indices are patched to 0,5,9 (CRC-valid). The save may refuse; if it saves, untouched layer
    records must stay byte-identical (no silent renumbering to 0,1,2) and the file must reload."""
    import struct, zlib
    f = str(tmp_path / 'g.3dm'); m = R.File3dm()
    for n in 'ABC':
        l = R.Layer(); l.Name = n; m.Layers.Add(l)
    m.Write(f, 7); d = bytearray(open(f, 'rb').read())
    for r, new in zip([r for r in write._table_records(bytes(d), 0x10000011)[2] if r[2] == 0x20008050], (0, 5, 9)):
        p0 = r[0] + 12; p = bytearray(d[p0:p0 + len(r[3])]); assert struct.unpack_from('<I', p, 61)[0] in (0, 1, 2)
        struct.pack_into('<I', p, 61, new)
        inner = [i for i in range(56, len(p) - 12) if struct.unpack_from('<I', p, i)[0] == 0x40008000][0]
        struct.pack_into('<I', p, len(p) - 20, zlib.crc32(bytes(p[56:inner] + p[inner + 28:len(p) - 20])))
        d[p0:p0 + len(p)] = p
    open(f, 'wb').write(d); before = bytes(d)
    assert R.File3dm.Read(f) is not None
    try: write.rename_layer(f, 'A', 'AA')
    except write.Refused: assert open(f, 'rb').read() == before; return
    ra = [r for r in write._table_records(before, 0x10000011)[2] if r[2] == 0x20008050]; rb = [r for r in write._table_records(open(f, 'rb').read(), 0x10000011)[2] if r[2] == 0x20008050]
    assert ra[1][3] == rb[1][3] and ra[2][3] == rb[2][3]
    assert [l.Name for l in R.File3dm.Read(f).Layers] == ['AA', 'B', 'C']


def test_unedited_table_chunks_byte_identical_after_rename_on_all_samples(tmp_path):
    """queue 110: on every public sample that saves, each top-level chunk of the tables no edit touches (materials, bitmaps, linetypes, ...) is byte-identical after a rename (properties table excluded: library version marker)"""
    n = 0
    for src in sorted(glob.glob(os.path.join(os.path.dirname(__file__), 'data*', '*.3dm'))):
        f = str(tmp_path / 'a.3dm'); shutil.copy(src, f); b = open(f, 'rb').read(); nm = R.File3dm.Read(f).Layers[0].Name
        try: write.rename_layer(f, nm, nm + '_x')
        except write.Refused: continue
        finally:
            for x in glob.glob(f + '.*'): os.remove(x)
        a = open(f, 'rb').read()
        for t in write.UNEDITED_TABLES:
            if t == 0x10000014: continue
            ob, oa = write._top_chunks(b, t), write._top_chunks(a, t)
            if ob is None or oa is None: continue
            assert [b[o:o + l] for o, l in ob] == [a[o:o + l] for o, l in oa], (os.path.basename(src), hex(t)); n += 1
    assert n >= 300


@pytest.mark.parametrize('new', ['alpha', 'ALPHA', 'Alpha ', ' Alpha', 'Alpha ', 'Alpha\t', ''])
def test_rename_colliding_or_padded_name_refused_bytes_unchanged(new, tmp_path):
    """queue 114: case-insensitive sibling collision, leading/trailing space, nbsp, tab, empty: refused with the file byte-identical and no .bak"""
    f = str(tmp_path / 'c.3dm'); m = R.File3dm()
    for n in ('Alpha', 'Beta'):
        l = R.Layer(); l.Name = n; m.Layers.Add(l)
    assert m.Write(f, 7); b = open(f, 'rb').read()
    with pytest.raises(write.Refused): write.rename_layer(f, 'Beta', new)
    assert open(f, 'rb').read() == b and os.listdir(str(tmp_path)) == ['c.3dm']


@pytest.mark.parametrize('target', ['os.replace', 'os.fsync', 'shutil.copy2', 'shutil.copymode'])
@pytest.mark.parametrize('exc', [OSError(28, 'No space left on device'), RuntimeError('boom')])
def test_failure_injected_at_each_save_step_leaves_original_and_no_tmp(target, exc, tmp_path, monkeypatch):
    """queue 117: an OSError (disk full) or an unexpected exception at replace / fsync / backup copy / permission copy: the original is byte-identical,
    no temp file, lock or half-written .bak remains (a .bak made before a failed replace is a complete copy)"""
    f = str(tmp_path / 'a.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f); b = open(f, 'rb').read(); lay = R.File3dm.Read(f).Layers[0].Name
    mod, fn = target.split('.'); obj = {'os': os, 'shutil': shutil}[mod]; real = getattr(obj, fn)
    def boom(*a, **k): raise exc
    monkeypatch.setattr(obj, fn, boom)
    with pytest.raises((write.Refused, OSError, RuntimeError)): write.rename_layer(f, lay, lay + '_x')
    monkeypatch.setattr(obj, fn, real)
    assert open(f, 'rb').read() == b
    left = sorted(os.listdir(str(tmp_path)))
    assert all(x == 'a.3dm' or x.startswith('a.3dm.bak') for x in left), left
    for x in left:
        if x.startswith('a.3dm.bak'): assert open(str(tmp_path / x), 'rb').read() == b


def test_hardlinked_source_refused_both_names_untouched(tmp_path):
    """queue 116: replacing a file with several hard links would silently detach the other names; refuse, both names byte-identical"""
    if os.name != 'posix': pytest.skip('posix hard links')
    f = str(tmp_path / 'a.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f); g = str(tmp_path / 'b.3dm'); os.link(f, g)
    b = open(f, 'rb').read(); lay = R.File3dm.Read(f).Layers[0].Name
    with pytest.raises(write.Refused, match='hard link'): write.rename_layer(f, lay, lay + '_x')
    assert open(f, 'rb').read() == b and open(g, 'rb').read() == b and sorted(os.listdir(str(tmp_path))) == ['a.3dm', 'b.3dm']


def test_reader_with_open_handle_sees_consistent_old_file_during_replace(tmp_path):
    """queue 115: a process that holds the file open and reads it slowly while a rename replaces it gets the complete old bytes (atomic replace, never a torn mix)"""
    if os.name != 'posix': pytest.skip('replace over an open file is posix semantics')
    f = str(tmp_path / 'a.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f); b = open(f, 'rb').read(); lay = R.File3dm.Read(f).Layers[0].Name
    with open(f, 'rb') as fh:
        first = fh.read(100)
        write.rename_layer(f, lay, lay + '_x')
        rest = fh.read()
    assert first + rest == b
    assert R.File3dm.Read(f).Layers[0].Name == lay + '_x'


def _crc_counts(b):
    """(flagged, valid): table records carrying the 0x8000 CRC flag, and how many have crc32(data[:-4]) equal to their last 4 bytes. Records with a nested chunk
    keep a CRC that skips the nested part, so they count as flagged but not valid; only the invalid count must never grow."""
    import struct, zlib
    o = 32; fl = ok = 0
    while o + 12 <= len(b):
        t, l = struct.unpack_from('<Iq', b, o)
        if t == 0x7fff: break
        if 0x10000010 <= t <= 0x10000026:
            r = o + 12
            while r + 12 <= o + 12 + l:
                t2, l2 = struct.unpack_from('<Iq', b, r)
                if t2 & 0x80000000: r += 12; continue
                if t2 & 0x8000 and l2 >= 4:
                    fl += 1; d = b[r + 12:r + 12 + l2]; ok += struct.unpack_from('<I', d, l2 - 4)[0] == zlib.crc32(d[:-4])
                r += 12 + l2
        o += 12 + l
    return fl, ok


def test_saved_outputs_have_no_more_crc_invalid_records_than_source(tmp_path):
    """queue 121: independent of the library, every CRC-flagged table record of a saved output verifies at least as well as in the source (a wrong CRC is what Rhino reports as a corrupt file)"""
    n = 0
    for src in sorted(glob.glob(os.path.join(os.path.dirname(__file__), 'data*', '*.3dm'))):
        f = str(tmp_path / 'a.3dm'); shutil.copy(src, f); b = open(f, 'rb').read(); nm = R.File3dm.Read(f).Layers[0].Name
        try: write.rename_layer(f, nm, nm + '_x')
        except write.Refused: continue
        finally:
            for x in glob.glob(f + '.*'): os.remove(x)
        (f0, o0), (f1, o1) = _crc_counts(b), _crc_counts(open(f, 'rb').read())
        assert f1 - o1 <= f0 - o0, (os.path.basename(src), (f0, o0), (f1, o1)); n += 1
    assert n >= 40


@pytest.mark.parametrize('how', ['append', 'same_size_same_mtime', 'delete'])
def test_source_swapped_by_another_process_during_edit_is_not_overwritten(how, tmp_path):
    """queue 120: another writer changes the source after it was read and before the replace (appended bytes, same-size content change with mtime restored, deleted):
    the save refuses (or fails) and never overwrites the newer file with a result computed from the stale one"""
    f = str(tmp_path / 'a.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f); lay = R.File3dm.Read(f).Layers[0].Name
    def edit(m):
        n = [l for l in m.Layers if l.Name == lay][0]; n.Name = lay + '_x'
        st = os.stat(f)
        if how == 'append': open(f, 'ab').write(b'\0' * 8)
        elif how == 'same_size_same_mtime':
            d = bytearray(open(f, 'rb').read()); d[-30] ^= 0xff; open(f, 'wb').write(d); os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns))
        else: os.remove(f)
    with pytest.raises((write.Refused, OSError)): write.edit_file(f, edit, lambda ds: ds == ['layers differs'])
    if how == 'delete': assert not os.path.exists(f)
    else:
        d = open(f, 'rb').read(); orig = open(os.path.join(D, 'V7-v7_my_brep.3dm'), 'rb').read()
        assert d != orig and len(d) in (len(orig), len(orig) + 8) and R.File3dm.Read(f).Layers[0].Name == lay
    assert not [x for x in os.listdir(str(tmp_path)) if x not in ('a.3dm',) and not x.startswith('a.3dm.bak')], os.listdir(str(tmp_path))


def test_rename_same_named_layers_under_different_parents_by_full_path(tmp_path):
    """queue 123: two layers named Sub under A and B: the bare name is ambiguous and refused (file untouched); 'B::Sub' renames only that one, other records byte-identical"""
    f = str(tmp_path / 'p.3dm'); m = R.File3dm()
    def add(n, parent=None):
        l = R.Layer(); l.Name = n
        if parent is not None: l.ParentLayerId = parent
        m.Layers.Add(l); return m.Layers[len(m.Layers) - 1].Id
    a = add('A'); b = add('B'); add('Sub', a); add('Sub', b); assert m.Write(f, 7)
    b0 = open(f, 'rb').read()
    with pytest.raises(write.Refused, match='2 times'): write.rename_layer(f, 'Sub', 'Sub2')
    assert open(f, 'rb').read() == b0
    write.rename_layer(f, 'B::Sub', 'Sub2')
    ls = R.File3dm.Read(f).Layers; par = {l.Name + str(i): str(l.ParentLayerId) for i, l in enumerate(ls)}
    assert [l.Name for l in ls] == ['A', 'B', 'Sub', 'Sub2']
    assert str(ls[2].ParentLayerId) == str(ls[0].Id) and str(ls[3].ParentLayerId) == str(ls[1].Id)
    ra = [r for r in write._table_records(b0, 0x10000011)[2] if r[2] == 0x20008050]; rb = [r for r in write._table_records(open(f, 'rb').read(), 0x10000011)[2] if r[2] == 0x20008050]
    assert [x[3] for x in ra[:3]] == [x[3] for x in rb[:3]]
    with pytest.raises(write.Refused): write.rename_layer(f, 'A::Nope', 'x')


def test_stale_lock_from_killed_save_is_cleared_fresh_lock_is_respected(tmp_path):
    """queue 124: a lock left by a killed save blocks a new save only while younger than LOCK_STALE_S; once older the save proceeds, result correct, lock released"""
    import time
    f = str(tmp_path / 'a.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f); b = open(f, 'rb').read(); lay = R.File3dm.Read(f).Layers[0].Name
    lk = f + '.3dmballet.lock'; open(lk, 'w').write(str(os.getpid()))
    with pytest.raises(write.Refused, match='in progress'): write.rename_layer(f, lay, lay + '_x')
    assert open(f, 'rb').read() == b and os.path.exists(lk)
    old = time.time() - write.LOCK_STALE_S - 60; os.utime(lk, (old, old))
    write.rename_layer(f, lay, lay + '_x')
    assert R.File3dm.Read(f).Layers[0].Name == lay + '_x' and not os.path.exists(lk)


@pytest.mark.parametrize('name', ['V7-v7_my_mesh.3dm', 'V7-v7_my_mesh_with_material.3dm', 'V7-v7_my_brep.3dm', 'V6-my_curves.3dm', 'V5-v5_my_mesh.3dm', 'V8-v8_caps_and_joins.3dm'])
def test_glb_export_after_rename_has_identical_geometry(name, tmp_path):
    """queue 127: the exported glb of a saved output has a byte-identical geometry buffer and, ignoring names, identical JSON (a rename must not touch geometry)"""
    import json, struct
    from tm3dballet import reader
    src = os.path.join(D, name)
    if not os.path.exists(src): pytest.skip('sample missing')
    f = str(tmp_path / 'a.3dm'); shutil.copy(src, f); nm = R.File3dm.Read(f).Layers[0].Name
    try: write.rename_layer(f, nm, nm + '_ZQ')
    except write.Refused: pytest.skip('refused by the gate')
    def glb(p, o):
        reader.to_glb(p, o); b = open(o, 'rb').read(); jl = struct.unpack_from('<I', b, 12)[0]; return json.loads(b[20:20 + jl]), b[20 + jl:]
    def strip(x):
        if isinstance(x, dict): return {k: strip(v) for k, v in x.items() if k != 'name'}
        return [strip(v) for v in x] if isinstance(x, list) else x
    j0, b0 = glb(src, str(tmp_path / 's.glb')); j1, b1 = glb(f, str(tmp_path / 'o.glb'))
    assert b0 == b1 and strip(j0) == strip(j1)

def test_backup_name_never_clobbers_sibling_files(tmp_path):
    """item 119: pre-existing sibling files named like backups (any case) stay byte-identical, backup gets a free name"""
    f = str(tmp_path / 'a.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f)
    src = open(f, 'rb').read()
    sib = {'a.3dm.bak': b'one', 'a.3dm.bak.1': b'two', 'A.3DM.bak': b'three', 'a.3dm.3dmballet.lock.x': b'four'}
    for n, c in sib.items(): (tmp_path / n).write_bytes(c)
    write.rename_layer(f, 'brep', 'R')
    for n, c in sib.items(): assert (tmp_path / n).read_bytes() == c
    assert (tmp_path / 'a.3dm.bak.2').read_bytes() == src
    assert sorted(os.listdir(tmp_path)) == sorted(list(sib) + ['a.3dm', 'a.3dm.bak.2'])


@pytest.mark.parametrize('f', FILES, ids=os.path.basename)
def test_every_table_except_layers_identical_after_rename(f, tmp_path):
    """item 118: all top-level tables (0x10000010..0x10000030) other than the layer table (0x10000011... plus its parent
    index effects) keep source record bytes; only the layer table may differ, and only in the renamed record"""
    m = R.File3dm.Read(f)
    if m is None or write.gate(m) or m.ArchiveVersion < 50: pytest.skip('n/a')
    g = str(tmp_path / 'a.3dm'); shutil.copy(f, g); lay = m.Layers[0].Name
    codes = [c for c in range(0x10000010, 0x10000031)]
    s0 = {c: _tbl(g, c) for c in codes}
    try: write.rename_layer(g, lay, lay + '_x')
    except write.Refused: pytest.skip('refused (also safe)')
    bad = []
    for c in codes:
        a, b = s0[c], _tbl(g, c)
        if a == b: continue
        if a is None or b is None: bad.append((hex(c), 'presence'))
        elif c == 0x10000014:   # properties: version marker and revision history may change by design (ALLOWED_RECORD_DIFFS)
            if len(b) < len(a) or len(b) > len(a) + 1: bad.append((hex(c), 'properties count'))   # library may ADD a revision history record, never drop one
        elif c == 0x10000011:   # layer table: same record count, at most one record changed
            if len(a) != len(b) or sum(x != y for x, y in zip(a, b)) > 1: bad.append((hex(c), 'layer table'))
        else: bad.append((hex(c), 'bytes'))
    assert not bad, bad


def test_two_concurrent_processes_one_wins_other_refused(tmp_path):
    """item 131: real race, 4 processes rename the same file to different names; every outcome is a valid file, no tmp or lock left"""
    import subprocess, sys
    f = str(tmp_path / 'a.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    code = ('import sys\nsys.path[:0]=[%r,%r]\nfrom tm3dballet import write\n'
            'try: write.rename_layer(%r, "brep", sys.argv[1]); print("OK")\nexcept write.Refused as e: print("REF")\n') % (root, os.path.join(root, '.deps'), f)
    ps = [subprocess.Popen([sys.executable, '-c', code, 'N%d' % i], stdout=subprocess.PIPE, text=True) for i in range(4)]
    outs = [p.communicate()[0].strip() for p in ps]
    assert all(o in ('OK', 'REF') for o in outs), outs
    nm = names(f)
    assert len(nm) == 1 and (nm[0] == 'brep' if outs.count('OK') == 0 else nm[0].startswith('N'))
    left = [x for x in os.listdir(tmp_path) if x.endswith('.tmp') or x.endswith('.lock')]
    assert not left, left
    for x in os.listdir(tmp_path):
        if '.bak' in x: assert names(str(tmp_path / x)) in (['brep'], [n for n in nm]) or names(str(tmp_path / x))[0].startswith('N')


def test_ten_sequential_renames_backups_distinct_and_valid(tmp_path):
    """item 132: chain of renames; each backup holds the state before its save; final equals source except the layer name"""
    f = str(tmp_path / 'a.3dm'); src = os.path.join(D, 'V7-v7_my_brep.3dm'); shutil.copy(src, f)
    seq = ['brep'] + ['L%d' % i for i in range(10)]
    for a, b in zip(seq, seq[1:]): write.rename_layer(f, a, b)
    assert names(f) == ['L9']
    baks = ['a.3dm.bak'] + ['a.3dm.bak.%d' % i for i in range(1, 10)]
    assert sorted(x for x in os.listdir(tmp_path) if '.bak' in x) == sorted(baks)
    assert [names(str(tmp_path / x)) for x in baks] == [[n] for n in seq[:-1]]
    assert len({open(str(tmp_path / x), 'rb').read() for x in baks}) == 10
    assert open(str(tmp_path / baks[0]), 'rb').read() == open(src, 'rb').read()
    m0, m1 = R.File3dm.Read(src), R.File3dm.Read(f)
    s0, s1 = write.snapshot(m0), write.snapshot(m1)
    assert write.diff(s0, s1) == ['layers differs']


@pytest.mark.parametrize('new', ['a\x00b', 'tab\tx', 'nl\nx', 'x' * 10000, '', '   ', 'é中\U0001F600', 'a::b'], ids=['nul', 'tab', 'newline', 'long10k', 'empty', 'spaces', 'unicode', 'sep'])
def test_odd_new_names_refused_or_exact_roundtrip(new, tmp_path):
    """items 133, 134: either refused with the original byte-identical and nothing left, or the saved name reads back exactly"""
    f = str(tmp_path / 'a.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f)
    before = open(f, 'rb').read()
    try: write.rename_layer(f, 'brep', new)
    except write.Refused:
        assert open(f, 'rb').read() == before and os.listdir(tmp_path) == ['a.3dm']; return
    assert names(f) == [new]
    assert not [x for x in os.listdir(tmp_path) if x.endswith(('.tmp', '.lock'))]
    assert new.strip() != '' and '\x00' not in new, 'empty/NUL names must be refused'


@pytest.mark.parametrize('name', ['x' * 251 + '.3dm', 'x' * 240 + '.3dm', 'trail.dot.3dm', 'sp ace é.3dm', '.hidden.3dm'], ids=['len255', 'len244', 'dots', 'unicode_space', 'hidden'])
def test_long_and_odd_file_names(name, tmp_path):
    """item 135: tmp, lock and backup names derive from the target; a name too long for them must be refused cleanly, never leave files or damage the source"""
    f = str(tmp_path / name); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f)
    before = open(f, 'rb').read()
    try: write.rename_layer(f, 'brep', 'R')
    except write.Refused:
        assert open(f, 'rb').read() == before and os.listdir(tmp_path) == [name]; return
    assert names(f) == ['R']
    left = [x for x in os.listdir(tmp_path) if x.endswith(('.tmp', '.lock'))]
    assert not left, left
    bak = [x for x in os.listdir(tmp_path) if '.bak' in x]
    assert len(bak) == 1 and open(str(tmp_path / bak[0]), 'rb').read() == before


def test_partial_backup_copy_leaves_no_truncated_bak(tmp_path, monkeypatch):
    """items 136, 137: disk fills up halfway through the backup copy: save refused, original identical, no truncated .bak (a half backup would be mistaken for a good one)"""
    f = str(tmp_path / 'a.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f); b = open(f, 'rb').read(); lay = R.File3dm.Read(f).Layers[0].Name
    def half(src, dst, **k):
        open(dst, 'wb').write(open(src, 'rb').read()[:len(b) // 2]); raise OSError(28, 'No space left on device')
    monkeypatch.setattr(shutil, 'copy2', half)
    with pytest.raises(write.Refused): write.rename_layer(f, lay, lay + '_x')
    assert open(f, 'rb').read() == b and os.listdir(str(tmp_path)) == ['a.3dm']


@pytest.mark.parametrize('mode', [0o644, 0o600, 0o664, 0o444, 0o755])
def test_mode_kept_mtime_updated_backup_keeps_source_mtime(mode, tmp_path):
    """item 138: permission bits of the original survive the replace; the output mtime is the save time; the backup keeps the source mtime"""
    if os.name != 'posix': pytest.skip('posix modes')
    f = str(tmp_path / 'a.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f)
    old = 1_500_000_000; os.utime(f, (old, old)); os.chmod(f, mode)
    try: write.rename_layer(f, 'brep', 'R')
    except write.Refused as e:
        assert mode == 0o444 and 'read-only' in str(e), e   # refusing a read-only source is also safe
        return
    assert (os.stat(f).st_mode & 0o777) == mode
    assert os.stat(f).st_mtime > old + 1000
    assert int(os.stat(f + '.bak').st_mtime) == old
    assert names(f) == ['R']


@pytest.mark.parametrize('n', [0, 1, 7, 32, 33, 49, 50, 100, 1000, 'half', 'minus1'])
def test_truncated_source_refused_nothing_left(n, tmp_path):
    """item 139: a source cut at any length is refused (never replaced by a 'repaired' file), bytes unchanged, directory unchanged"""
    full = open(os.path.join(D, 'V7-v7_my_brep.3dm'), 'rb').read()
    k = len(full) // 2 if n == 'half' else len(full) - 1 if n == 'minus1' else n
    f = str(tmp_path / 'a.3dm'); open(f, 'wb').write(full[:k])
    with pytest.raises(write.Refused): write.rename_layer(f, 'brep', 'R')
    assert open(f, 'rb').read() == full[:k] and os.listdir(tmp_path) == ['a.3dm']


def test_directory_fsynced_after_replace_and_failure_is_harmless(tmp_path, monkeypatch):
    """item 140: the directory is fsynced after os.replace (posix); a failing directory fsync never fails or damages the save"""
    if os.name != 'posix': pytest.skip('posix')
    f = str(tmp_path / 'a.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f)
    calls = []; real = os.fsync; rep = os.replace; order = []
    monkeypatch.setattr(os, 'replace', lambda a, b: (order.append('replace'), rep(a, b))[1])
    def fs(fd):
        if os.path.isdir('/proc/self/fd/%d' % fd): order.append('dirfsync'); calls.append(fd)
        return real(fd)
    monkeypatch.setattr(os, 'fsync', fs)
    write.rename_layer(f, 'brep', 'R1')
    assert calls and order.index('dirfsync') > order.index('replace')
    def bad(fd):
        if os.path.isdir('/proc/self/fd/%d' % fd): raise OSError(5, 'EIO')
        return real(fd)
    monkeypatch.setattr(os, 'fsync', bad)
    write.rename_layer(f, 'R1', 'R2'); assert names(f) == ['R2']


REGRESS = sorted(glob.glob(os.path.join(os.path.dirname(__file__), 'regress', '*.3dm')))

@pytest.mark.parametrize('f', REGRESS, ids=os.path.basename)
def test_regress_files_rename_never_traceback_original_intact(f, tmp_path):
    """item 142: each permanent fuzz/hang regression file: rename is refused or verified; never an unexpected exception, source intact unless saved and valid"""
    g = str(tmp_path / 'a.3dm'); shutil.copy(f, g); before = open(g, 'rb').read()
    try:
        m = R.File3dm.Read(g)
        lay = m.Layers[0].Name if m is not None and len(m.Layers) else 'x'
    except Exception: lay = 'x'
    try: write.rename_layer(g, lay, lay + '_x')
    except write.Refused:
        assert open(g, 'rb').read() == before and os.listdir(tmp_path) == ['a.3dm']; return
    assert lay + '_x' in names(g) or lay == 'x'
    assert open(g + '.bak', 'rb').read() == before


def test_case_only_rename_accepted_and_back(tmp_path):
    """item 143: renaming a layer to the same name in different case is a real change (not a self-collision) and round-trips"""
    f = str(tmp_path / 'a.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f)
    assert write.rename_layer(f, 'brep', 'BREP') == ['layers differs'] and names(f) == ['BREP']
    assert write.rename_layer(f, 'BREP', 'Brep') == ['layers differs'] and names(f) == ['Brep']
    assert write.rename_layer(f, 'Brep', 'brep') == ['layers differs'] and names(f) == ['brep']
    # same name unchanged: nothing to do, must not corrupt
    try: write.rename_layer(f, 'brep', 'brep')
    except write.Refused: pass
    assert names(f) == ['brep']


def test_2000_layers_rename_one_others_identical_and_fast(tmp_path):
    """item 144: synthetic file with 2000 layers (3 levels deep) and a few objects: rename one, the other 1999 layer records identical, bounded time"""
    import time, uuid
    m = R.File3dm(); ids = []
    for i in range(2000):
        l = R.Layer(); l.Name = 'L%04d' % (i % 500)           # many repeated names under different parents
        l.Id = uuid.uuid4()
        if i >= 20: l.ParentLayerId = ids[(i * 7) % min(i, 20)] if i % 3 else ids[i - 1] if i % 50 else uuid.UUID(int=0)
        m.Layers.Add(l); ids.append(l.Id)
    for i in range(30):
        a = R.ObjectAttributes(); a.LayerIndex = (i * 61) % 2000; m.Objects.AddPoint(R.Point3d(i, 0, 0), a)
    f = str(tmp_path / 'big.3dm'); assert m.Write(f, 7)
    s0 = R.File3dm.Read(f); recs0 = [l.Encode() for l in s0.Layers]; lay = s0.Layers[1000]
    full = lay.Name; t = time.time()
    try: write.rename_layer(f, full, 'Renamed')
    except write.Refused as e:
        assert os.listdir(tmp_path) == ['big.3dm'], e
        pytest.skip('refused (safe): %s' % str(e)[:80]); return
    assert time.time() - t < 120
    m1 = R.File3dm.Read(f); assert len(m1.Layers) == 2000
    diff = [i for i, (a, b) in enumerate(zip(recs0, [l.Encode() for l in m1.Layers])) if a != b]
    assert len(diff) == 1 and m1.Layers[diff[0]].Name == 'Renamed', diff
    assert len(m1.Objects) == 30


def test_unwritable_tmpdir_does_not_matter_tmp_is_next_to_source(tmp_path, monkeypatch):
    """item 153: temp file lives beside the source (same filesystem, atomic replace) so a broken TMPDIR changes nothing"""
    bad = tmp_path / 'nope'; monkeypatch.setenv('TMPDIR', str(bad)); monkeypatch.setattr(tempfile, 'tempdir', None)
    d = tmp_path / 'w'; d.mkdir(); f = str(d / 'a.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f)
    write.rename_layer(f, 'brep', 'R'); assert names(f) == ['R'] and not bad.exists()


def test_symlinked_source_target_replaced_link_kept_no_stray_files(tmp_path):
    """item 155: save through a symlink in another directory: the link stays a link to the same target, the target holds the new data, the link directory gets no files"""
    if os.name != 'posix': pytest.skip('posix symlinks')
    t = tmp_path / 'real'; t.mkdir(); l = tmp_path / 'links'; l.mkdir()
    tf = str(t / 'a.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), tf); lf = str(l / 'a.3dm'); os.symlink(tf, lf)
    before = open(tf, 'rb').read()
    try: write.rename_layer(lf, 'brep', 'R')
    except write.Refused:
        assert os.path.islink(lf) and open(tf, 'rb').read() == before and os.listdir(t) == ['a.3dm'] and os.listdir(l) == ['a.3dm']; return
    assert os.path.islink(lf) and os.path.realpath(lf) == os.path.realpath(tf)
    assert names(tf) == ['R'] and os.listdir(l) == ['a.3dm']
    assert sorted(os.listdir(t)) == ['a.3dm', 'a.3dm.bak'] and open(str(t / 'a.3dm.bak'), 'rb').read() == before


@pytest.mark.parametrize('dmode', [0o1777, 0o2755, 0o3775], ids=['sticky', 'setgid', 'both'])
def test_sticky_and_setgid_directories(dmode, tmp_path):
    """item 154: the save works in a sticky/setgid directory, the new file keeps the original permission bits (no special bits leak), owner unchanged"""
    if os.name != 'posix': pytest.skip('posix')
    d = tmp_path / 'd'; d.mkdir(); os.chmod(d, dmode)
    f = str(d / 'a.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f); os.chmod(f, 0o640); before = os.stat(f)
    write.rename_layer(f, 'brep', 'R')
    st = os.stat(f)
    assert names(f) == ['R'] and (st.st_mode & 0o7777) == 0o640 and st.st_uid == before.st_uid
    assert sorted(os.listdir(d)) == ['a.3dm', 'a.3dm.bak']


@pytest.mark.parametrize('new', ['  lead', 'trail  ', ' both ', 'café', 'café', 'Å', 'Å', 'a\r\nb', '﻿bom', 'é' * 50], ids=['lead', 'trail', 'both', 'nfc', 'nfd', 'ring_nfd', 'ring_nfc', 'crlf', 'bom', 'nfd_long'])
def test_names_with_spaces_and_normalization_roundtrip_exactly(new, tmp_path):
    """item 160: no trimming, normalising or newline conversion: NFC and NFD forms stay distinct; refused is also acceptable"""
    f = str(tmp_path / 'a.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f); before = open(f, 'rb').read()
    try: write.rename_layer(f, 'brep', new)
    except write.Refused:
        assert open(f, 'rb').read() == before and os.listdir(tmp_path) == ['a.3dm']; return
    assert names(f) == [new]


def test_reader_polling_during_saves_sees_only_old_or_new_names(tmp_path):
    """item 158: a viewer process re-reading the file in a loop while three saves happen never sees a partial file (atomic replace)"""
    import subprocess, sys, time
    f = str(tmp_path / 'a.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    code = ('import sys,time\nsys.path[:0]=[%r,%r]\nimport rhino3dm as R\nend=time.time()+%d\nseen=set();bad=0\n'
            'while time.time()<end:\n    m=R.File3dm.Read(%r)\n    if m is None or len(m.Layers)!=1: bad+=1\n    else: seen.add(m.Layers[0].Name)\n'
            'print(bad, sorted(seen))\n') % (root, os.path.join(root, '.deps'), 25, f)
    p = subprocess.Popen([sys.executable, '-c', code], stdout=subprocess.PIPE, text=True); time.sleep(1)
    for a, b in [('brep', 'P1'), ('P1', 'P2'), ('P2', 'P3')]: write.rename_layer(f, a, b)
    out = p.communicate()[0].strip(); bad, seen = out.split(' ', 1)
    assert bad == '0', out
    assert set(eval(seen)) <= {'brep', 'P1', 'P2', 'P3'} and 'P3' in eval(seen) or 'P3' in names(f), out


def test_group_of_original_kept_in_setgid_directory(tmp_path):
    """item 156: file group adm in a setgid directory of group kvm (or any two groups of this user): the saved file keeps the original group"""
    if os.name != 'posix': pytest.skip('posix')
    gs = [g for g in os.getgroups() if g != os.getgid()]
    if len(gs) < 2: pytest.skip('need two supplementary groups')
    d = tmp_path / 'd'; d.mkdir(); os.chown(d, -1, gs[0]); os.chmod(d, 0o2775)
    f = str(d / 'a.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f); os.chown(f, -1, gs[1])
    assert os.stat(f).st_gid == gs[1]
    write.rename_layer(f, 'brep', 'R')
    assert names(f) == ['R'] and os.stat(f).st_gid == gs[1]
    assert os.stat(f + '.bak').st_gid in (gs[1], gs[0])


def test_read_only_filesystem_refused_nothing_created(tmp_path):
    """item 157: source on a read-only mount (user namespace bind mount, no sudo): refused, bytes unchanged, directory unchanged"""
    import subprocess, sys, shutil as sh
    if sys.platform != 'linux' or not sh.which('unshare'): pytest.skip('needs linux unshare')
    d = tmp_path / 'ro'; d.mkdir(); f = d / 'a.3dm'; sh.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f); before = f.read_bytes()
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    py = ('import sys,os\nsys.path[:0]=[%r,%r]\nfrom tm3dballet import write\n'
          'try: write.rename_layer(%r,"brep","R"); print("SAVED")\nexcept write.Refused as e: print("REFUSED")\n') % (root, os.path.join(root, '.deps'), str(f))
    sh_cmd = 'mount --bind "$1" "$1" && mount -o remount,bind,ro "$1" && ! touch "$1/x" 2>/dev/null && exec "$2" -c "$3"'
    r = subprocess.run(['unshare', '-rm', 'sh', '-c', sh_cmd, 'sh', str(d), sys.executable, py], capture_output=True, text=True)
    if 'SAVED' not in r.stdout and 'REFUSED' not in r.stdout: pytest.skip('user namespaces unavailable: %s' % r.stderr[:100])
    assert 'REFUSED' in r.stdout and f.read_bytes() == before and os.listdir(d) == ['a.3dm']



def test_lock_of_dead_pid_is_cleared_at_once_live_pid_respected(tmp_path):
    """a save killed by SIGKILL leaves its lock; the next save must not wait LOCK_STALE_S. A lock of a live process, or with junk content, still blocks."""
    if os.name != 'posix': pytest.skip('posix')
    import subprocess, sys
    f = str(tmp_path / 'a.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f); lk = f + '.3dmballet.lock'
    p = subprocess.Popen([sys.executable, '-c', 'pass']); p.wait()
    open(lk, 'w').write(str(p.pid))
    write.rename_layer(f, 'brep', 'R1'); assert names(f) == ['R1'] and not os.path.exists(lk)
    for content in (str(os.getpid()), 'junk', ''):
        open(lk, 'w').write(content)
        with pytest.raises(write.Refused): write.rename_layer(f, 'R1', 'R2')
        assert names(f) == ['R1']; os.remove(lk)


def test_source_on_other_filesystem_than_tmpdir_stays_in_source_dir(tmp_path, monkeypatch):
    """item 162: TMPDIR on another fs (/dev/shm) than the source: tmp is created beside the source, so os.replace never crosses devices"""
    if not os.path.isdir('/dev/shm') or os.stat('/dev/shm').st_dev == os.stat(tmp_path).st_dev: pytest.skip('no second filesystem')
    monkeypatch.setenv('TMPDIR', '/dev/shm'); tempfile.tempdir = None
    try:
        f = str(tmp_path / 'a.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f)
        write.rename_layer(f, 'brep', 'X'); assert names(f) == ['X']
        assert sorted(os.listdir(tmp_path)) == ['a.3dm', 'a.3dm.bak']
    finally: tempfile.tempdir = None


def test_concurrent_save_and_restore_one_wins_file_valid(tmp_path):
    """item 163: rename and restore-backup started together on the same file: the lock serializes them; the file is always a valid old or new version"""
    import threading
    f = str(tmp_path / 'a.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f)
    write.rename_layer(f, 'brep', 'N1')                       # makes a .bak with the original
    res = []
    def a():
        try: write.rename_layer(f, 'N1', 'N2'); res.append('rename')
        except write.Refused: res.append('rename refused')
    def b():
        try: write.restore_backup(f); res.append('restore')
        except write.Refused: res.append('restore refused')
    ts = [threading.Thread(target=x) for x in (a, b)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert len(res) == 2 and names(f) in (['N1'], ['N2'], ['brep'])
    assert not any(n.endswith('.lock') or n.endswith('.tmp') for n in os.listdir(tmp_path))
    for n in os.listdir(tmp_path):
        if '.bak' in n: assert len(names(str(tmp_path / n))) == 1


def test_restore_with_symlinked_file_and_symlinked_backup(tmp_path):
    """item 164: restore through a symlink replaces the target and keeps the link; a symlinked newest backup is refused and nothing changes"""
    if os.name != 'posix': pytest.skip('posix')
    real = tmp_path / 'real'; real.mkdir(); link = tmp_path / 'link.3dm'
    f = str(real / 'a.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f); os.symlink(f, link)
    write.rename_layer(f, 'brep', 'N1')
    write.restore_backup(str(link)); assert os.path.islink(link) and names(f) == ['brep'] and sorted(os.listdir(tmp_path)) == ['link.3dm', 'real']
    # newest backup replaced by a symlink to another file
    other = str(tmp_path / 'other.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), other)
    baks = sorted(n for n in os.listdir(real) if '.bak' in n); top = max(baks, key=lambda n: int(n.rsplit('.', 1)[1]) if n.rsplit('.', 1)[1].isdigit() else 0)
    os.remove(real / top); os.symlink(other, real / top)
    before = open(f, 'rb').read()
    with pytest.raises(write.Refused): write.restore_backup(f)
    assert open(f, 'rb').read() == before and not any(n.endswith(('.lock', '.tmp')) for n in os.listdir(real))


@pytest.mark.parametrize('bad', ['a\0b', '\ud800x', '', 'x' * 10000, 'a::b', 'a\nb', 'a\tb', '\udfff'])
def test_hostile_names_refused_with_Refused_and_original_intact(bad, tmp_path):
    """item 166: a lone surrogate used to escape as a raw TypeError; every hostile name must be a clean refusal"""
    f = str(tmp_path / 'a.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f); before = open(f, 'rb').read()
    with pytest.raises(write.Refused): write.rename_layer(f, 'brep', bad)
    assert open(f, 'rb').read() == before and os.listdir(tmp_path) == ['a.3dm']


def test_backup_names_taken_by_directory_or_dangling_symlink_are_skipped(tmp_path):
    """item 170: a.3dm.bak is a directory and a.3dm.bak.1 a dangling symlink: the backup goes to .bak.2, nothing is written through the symlink"""
    if os.name != 'posix': pytest.skip('posix')
    f = str(tmp_path / 'a.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f); orig = open(f, 'rb').read()
    os.mkdir(f + '.bak'); target = str(tmp_path / 'elsewhere'); os.symlink(target, f + '.bak.1')
    write.rename_layer(f, 'brep', 'NEW')
    assert open(f + '.bak.2', 'rb').read() == orig and os.path.isdir(f + '.bak') and not os.path.exists(target) and names(f) == ['NEW']


def test_thirty_saves_every_backup_valid_and_distinct_names(tmp_path):
    """item 171: backups accumulate one per save (no pruning, documented); each is a valid file holding the layer name of its time"""
    f = str(tmp_path / 'a.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f); cur = 'brep'
    for i in range(30): write.rename_layer(f, cur, 'N%d' % i); cur = 'N%d' % i
    baks = sorted(n for n in os.listdir(tmp_path) if '.bak' in n); assert len(baks) == 30
    seen = sorted(names(str(tmp_path / n))[0] for n in baks); assert seen == sorted(['brep'] + ['N%d' % i for i in range(29)])


def test_zero_padded_tail_refused(tmp_path):
    """item 174: 4 KB of zero bytes after the end-of-file chunk: refused, file untouched"""
    f = str(tmp_path / 'a.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f)
    with open(f, 'ab') as h: h.write(b'\0' * 4096)
    before = open(f, 'rb').read()
    with pytest.raises(write.Refused): write.rename_layer(f, 'brep', 'N')
    assert open(f, 'rb').read() == before and os.listdir(tmp_path) == ['a.3dm']


def test_restore_with_truncated_newest_backup_refused_file_untouched(tmp_path):
    """item 176: newest backup truncated to 1000 bytes: restore refuses, file byte-identical, no temp or lock left"""
    f = str(tmp_path / 'a.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f); write.rename_layer(f, 'brep', 'N')
    os.truncate(f + '.bak', 1000); before = open(f, 'rb').read()
    with pytest.raises(write.Refused): write.restore_backup(f)
    assert open(f, 'rb').read() == before and sorted(os.listdir(tmp_path)) == ['a.3dm', 'a.3dm.bak']


def test_fifo_and_directory_sources_refused_without_hanging(tmp_path):
    """item 178: a FIFO or directory named like a .3dm is refused as not a regular file (a FIFO must not block the reader)"""
    if os.name != 'posix': pytest.skip('posix')
    ff = str(tmp_path / 'f.3dm'); os.mkfifo(ff); dd = str(tmp_path / 'd.3dm'); os.mkdir(dd)
    for p in (ff, dd):
        with pytest.raises(write.Refused, match='not a regular file'): write.rename_layer(p, 'x', 'y')
    assert sorted(os.listdir(tmp_path)) == ['d.3dm', 'f.3dm']


@pytest.mark.parametrize('name', ['V8-v8_caps_and_joins.3dm', 'V8-v8_section_hatch.3dm'])
def test_rename_on_v8_samples_roundtrip(name, tmp_path):
    """item 177: V8 archive files: rename accepted or cleanly refused; never a traceback; original intact on refusal"""
    src = os.path.join(D, '..', 'data_ext', name) if not os.path.exists(os.path.join(D, name)) else os.path.join(D, name)
    f = str(tmp_path / 'a.3dm'); shutil.copy(src, f); before = open(f, 'rb').read(); lay = R.File3dm.Read(f).Layers[0].Name
    try: write.rename_layer(f, lay, 'Zz'); assert names(f)[0] == 'Zz' and open(f + '.bak', 'rb').read() == before
    except write.Refused: assert open(f, 'rb').read() == before


def test_output_modified_after_gate_is_not_installed(tmp_path, monkeypatch):
    """item 186: the temp file is flipped by one byte after the gate verified it (simulated at the backup step, which runs after the gate and before the replace): refused, original intact, no leftovers"""
    f = str(tmp_path / 'a.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f); before = open(f, 'rb').read()
    real = shutil.copy2
    def evil(src, dst, *a, **k):
        r = real(src, dst, *a, **k)
        for n in os.listdir(tmp_path):
            if n.endswith('.tmp'):
                with open(tmp_path / n, 'r+b') as h: h.seek(200); c = h.read(1); h.seek(200); h.write(bytes([c[0] ^ 1]))
        return r
    monkeypatch.setattr(shutil, 'copy2', evil)
    with pytest.raises(write.Refused, match='changed after'): write.rename_layer(f, 'brep', 'N')
    monkeypatch.undo()
    assert open(f, 'rb').read() == before and sorted(os.listdir(tmp_path)) in (['a.3dm'], ['a.3dm', 'a.3dm.bak'])


def test_rename_in_100_deep_layer_chain_only_that_segment_changes(tmp_path):
    """item 182: 100 nested layers; rename the 50th: ids and parent ids unchanged, full paths change only by that segment"""
    import uuid
    f = str(tmp_path / 'deep.3dm'); m = R.File3dm(); par = uuid.UUID(int=0)
    for i in range(100):
        l = R.Layer(); l.Name = 'L%d' % i; l.Id = uuid.uuid4(); l.ParentLayerId = par; m.Layers.Add(l); par = l.Id
    m.Write(f, 7)
    def paths(p):
        ls = R.File3dm.Read(p).Layers; by = {str(l.Id): l for l in ls}
        def full(l):
            n = []
            while True:
                n.append(l.Name); q = str(l.ParentLayerId)
                if q not in by: break
                l = by[q]
            return '::'.join(reversed(n))
        return [(str(l.Id), str(l.ParentLayerId), full(l)) for l in ls]
    a = paths(f); write.rename_layer(f, 'L50', 'MID'); b = paths(f)
    assert all(x[:2] == y[:2] for x, y in zip(a, b))
    assert [y[2] for y in b] == [x[2].replace('L50', 'MID', 1) if i >= 50 else x[2] for i, x in enumerate(a)]


def test_backup_with_flipped_byte_refused_and_removed(tmp_path, monkeypatch):
    """item 189: the backup copy is compared by hash, not only by size; a flipped byte in the copy refuses the save, removes the bad backup, original intact"""
    f = str(tmp_path / 'a.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f); before = open(f, 'rb').read(); real = shutil.copy2
    def evil(src, dst, *a, **k):
        r = real(src, dst, *a, **k)
        if str(dst).endswith('.bak'):
            with open(dst, 'r+b') as h: h.seek(100); c = h.read(1); h.seek(100); h.write(bytes([c[0] ^ 1]))
        return r
    monkeypatch.setattr(shutil, 'copy2', evil)
    with pytest.raises(write.Refused, match='backup'): write.rename_layer(f, 'brep', 'N')
    monkeypatch.undo()
    assert open(f, 'rb').read() == before and os.listdir(tmp_path) == ['a.3dm']
