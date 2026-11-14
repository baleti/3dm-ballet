import os, re, subprocess, sys, urllib.request
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
