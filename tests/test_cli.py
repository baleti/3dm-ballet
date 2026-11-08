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
