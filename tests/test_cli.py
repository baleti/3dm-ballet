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
