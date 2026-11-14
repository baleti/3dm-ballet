import json, os, re, subprocess, sys, urllib.request
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def test_serve_endpoints():
    sys.path.insert(0, ROOT)
    from tm3dballet import cli
    if not cli.find_three(): import pytest; pytest.skip('no three.js available')
    p = subprocess.Popen([os.path.join(ROOT, '3dm-ballet'), os.path.join(ROOT, 'tests', 'data', 'V7-v7_my_mesh.3dm'), '--no-browser'], stdout=subprocess.PIPE, text=True)
    try:
        u = next(m.group(0) for l in p.stdout for m in [re.search(r'http://\S+', l)] if m)
        for q in ('', 'model.glb', 'three/three.module.js'): assert urllib.request.urlopen(u + q).status == 200
        assert urllib.request.urlopen(u + 'model.glb').read()[:4] == b'glTF'
    finally: p.terminate()


def test_rename_layer_dry_run_then_overwrite(tmp_path):
    import shutil, rhino3dm as R
    from tm3dballet import cli
    src = os.path.join(os.path.dirname(__file__), 'data', 'V7-v7_my_brep.3dm'); f = str(tmp_path / 'a.3dm'); shutil.copy(src, f)
    before = open(f, 'rb').read(); lay = R.File3dm.Read(f).Layers[0].Name
    assert cli.main(['rename-layer', f, lay, 'zz']) == 0 and open(f, 'rb').read() == before      # default: never writes
    assert cli.main(['rename-layer', f, 'nope', 'zz', '--overwrite']) == 1 and open(f, 'rb').read() == before
    assert cli.main(['rename-layer', f, lay, 'zz', '--overwrite']) == 0
    assert R.File3dm.Read(f).Layers[0].Name == 'zz' and open(f + '.bak', 'rb').read() == before


def test_cli_rename_layer_by_full_path_dry_run_and_usage(tmp_path):
    """queue 125: CLI accepts the Parent::Child form (dry run, source untouched) and its usage line names it"""
    import shutil, rhino3dm as R
    f = str(tmp_path / 'p.3dm'); m = R.File3dm()
    def add(n, parent=None):
        l = R.Layer(); l.Name = n
        if parent is not None: l.ParentLayerId = parent
        m.Layers.Add(l); return m.Layers[len(m.Layers) - 1].Id
    a = add('A'); b = add('B'); add('Sub', a); add('Sub', b); assert m.Write(f, 7); before = open(f, 'rb').read()
    cli = os.path.join(ROOT, '3dm-ballet')
    r = subprocess.run([cli, 'rename-layer', f, 'Sub', 'S2'], capture_output=True, text=True); assert r.returncode == 1 and '2 times' in r.stdout
    r = subprocess.run([cli, 'rename-layer', f, 'B::Sub', 'S2'], capture_output=True, text=True); assert r.returncode == 0 and 'dry run OK' in r.stdout, r.stdout + r.stderr
    r = subprocess.run([cli, 'rename-layer', f], capture_output=True, text=True); assert r.returncode == 2 and 'Parent::Child' in r.stdout
    assert open(f, 'rb').read() == before

def test_cli_exit_codes_per_refusal_class(tmp_path, capsys):
    """item 122: usage=2, every refusal=1 with 'REFUSED, file untouched' on stdout, source bytes unchanged, success=0"""
    import shutil, rhino3dm as R
    from tm3dballet import cli
    D = os.path.join(os.path.dirname(__file__), 'data')
    def put(n, src='V7-v7_my_brep.3dm'):
        p = str(tmp_path / n); shutil.copy(os.path.join(D, src), p); return p
    def run(f, *a):
        before = open(f, 'rb').read(); rc = cli.main(['rename-layer', f] + list(a)); out = capsys.readouterr().out
        assert open(f, 'rb').read() == before; return rc, out
    f = put('a.3dm'); lay = R.File3dm.Read(f).Layers[0].Name
    rc, out = run(f, 'nope', 'x', '--overwrite'); assert rc == 1 and 'REFUSED, file untouched' in out          # edit refused
    old = put('old.3dm', 'V1-v1_DeformCubes.3dm'); rc, out = run(old, 'a', 'b', '--overwrite'); assert rc == 1 and 'REFUSED' in out  # gate
    open(f + '.3dmballet.lock', 'w').close(); rc, out = run(f, lay, 'x', '--overwrite'); assert rc == 1 and 'in progress' in out      # lock held
    os.remove(f + '.3dmballet.lock')
    os.link(f, str(tmp_path / 'hl.3dm')); rc, out = run(f, lay, 'x', '--overwrite'); assert rc == 1 and 'REFUSED' in out              # hardlink
    os.remove(str(tmp_path / 'hl.3dm'))
    if os.geteuid() != 0:
        d = tmp_path / 'ro'; d.mkdir(); g = str(d / 'a.3dm'); shutil.copy(f, g); os.chmod(d, 0o555)
        try: rc, out = run(g, lay, 'x', '--overwrite'); assert rc == 1 and 'REFUSED' in out                                           # readonly dir
        finally: os.chmod(d, 0o755)
    assert cli.main(['rename-layer', f]) == 2


def test_restore_backup_roundtrip_and_refusals(tmp_path, capsys):
    """item 141: restore puts the newest backup back byte for byte, keeps the replaced file as a new backup, refuses missing/damaged backups"""
    import shutil
    from tm3dballet import cli
    src = os.path.join(os.path.dirname(__file__), 'data', 'V7-v7_my_brep.3dm'); f = str(tmp_path / 'a.3dm'); shutil.copy(src, f)
    orig = open(f, 'rb').read()
    assert cli.main(['restore-backup', f]) == 1 and open(f, 'rb').read() == orig            # no backup yet
    assert cli.main(['rename-layer', f, 'brep', 'R1', '--overwrite']) == 0
    assert cli.main(['rename-layer', f, 'R1', 'R2', '--overwrite']) == 0
    r2 = open(f, 'rb').read(); capsys.readouterr()
    assert cli.main(['restore-backup', f]) == 0                                              # newest backup = state with layer R1
    import rhino3dm as R
    assert R.File3dm.Read(f).Layers[0].Name == 'R1'
    assert open(str(tmp_path / 'a.3dm.bak.2'), 'rb').read() == r2                            # the replaced file is kept: restore is undoable
    assert open(str(tmp_path / 'a.3dm.bak'), 'rb').read() == orig
    assert not [x for x in os.listdir(tmp_path) if x.endswith(('.tmp', '.lock'))]
    bad = str(tmp_path / 'b.3dm'); shutil.copy(src, bad); before = open(bad, 'rb').read()
    open(bad + '.bak', 'wb').write(orig[:len(orig) // 2])                                    # truncated backup
    assert cli.main(['restore-backup', bad]) == 1 and open(bad, 'rb').read() == before
    assert sorted(x for x in os.listdir(tmp_path) if x.startswith('b.')) == ['b.3dm', 'b.3dm.bak']


def test_info_of_saved_file_equals_source_except_layer_name(tmp_path, capsys):
    """item 165: CLI info of a file saved by the guard is the same as of the source, apart from the renamed layer"""
    import shutil
    sys.path.insert(0, ROOT)
    from tm3dballet import cli, write
    import rhino3dm as R
    src = os.path.join(ROOT, 'tests', 'data', 'V7-v7_my_brep.3dm'); f = str(tmp_path / 'a.3dm'); shutil.copy(src, f)
    lay = R.File3dm.Read(f).Layers[0].Name
    def info(p):
        return subprocess.run([os.path.join(ROOT, '3dm-ballet'), 'info', p], capture_output=True, text=True)
    a = info(src)
    assert cli.main(['rename-layer', f, lay, 'zzname', '--overwrite']) == 0
    b = info(f)
    assert a.returncode == b.returncode
    ja, jb = json.loads(a.stdout), json.loads(b.stdout)
    ja.pop('file'); jb.pop('file')
    sa, sb = json.dumps(ja, sort_keys=True), json.dumps(jb, sort_keys=True)
    assert sa.replace(json.dumps(lay), '"<L>"') == sb.replace('"zzname"', '"<L>"'), (a.stdout, b.stdout)
    assert sa != sb


def test_cli_rename_path_with_spaces_unicode_and_leading_dash(tmp_path):
    """item 172: directory with spaces and an accent, file name starting with a dash (given as ./name)"""
    import shutil
    d = tmp_path / 'sp ace é'; d.mkdir(); f = d / '-x y.3dm'; shutil.copy(os.path.join(ROOT, 'tests', 'data', 'V7-v7_my_brep.3dm'), f)
    r = subprocess.run([os.path.join(ROOT, '3dm-ballet'), 'rename-layer', str(f), 'brep', 'N', '--overwrite'], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert sorted(os.listdir(d)) == ['-x y.3dm', '-x y.3dm.bak']


def test_cli_rename_trailing_bytes_after_last_chunk_refused(tmp_path):
    """item 173: bytes appended after the end-of-file chunk: refused (the writer would drop them), file untouched"""
    import shutil
    f = tmp_path / 't.3dm'; shutil.copy(os.path.join(ROOT, 'tests', 'data', 'V7-v7_my_brep.3dm'), f)
    with open(f, 'ab') as h: h.write(b'TRAILING-JUNK')
    before = f.read_bytes()
    r = subprocess.run([os.path.join(ROOT, '3dm-ballet'), 'rename-layer', str(f), 'brep', 'N', '--overwrite'], capture_output=True, text=True)
    assert r.returncode == 1 and 'REFUSED' in r.stdout and f.read_bytes() == before and os.listdir(tmp_path) == ['t.3dm']
