import glob, os, shutil, pytest
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
    open(f + '.3dmballet.lock', 'w').write('999')
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
        with pytest.raises(write.Refused): write.rename_layer(f, lay, lay + '_x')
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
    lk = f + '.3dmballet.lock'; open(lk, 'w').write('12345')
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
