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
    f = str(tmp_path / 'a.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), f)
    before = open(f, 'rb').read()
    def evil(m): m.Layers[0].Name = 'x'; m.Objects[0].Attributes.Name = 'sneaky'  # attribute edit not allowed by expect
    # attribute edits on a copy of Objects are not written back by rhino3dm, so also force a layer + count mismatch
    with pytest.raises(write.Refused): write.edit_file(f, lambda m: (evil(m), m.Layers.Add(R.Layer())), lambda ds: ds == ['layers differs'])
    assert open(f, 'rb').read() == before

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
    with pytest.raises(write.Refused, match='user record'): write.rename_layer(f, lay, lay + '_x')
    assert open(f, 'rb').read() == before
