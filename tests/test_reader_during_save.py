import os, shutil, threading, rhino3dm as R
from tm3dballet import write
SRC = os.path.join(os.path.dirname(__file__), 'data', 'V7-v7_my_brep.3dm')

def test_polling_reader_never_sees_partial_file(tmp_path):
    p = str(tmp_path / 'a.3dm'); shutil.copy(SRC, p); full = os.path.getsize(p)
    stop = threading.Event(); bad = []; seen = set()
    def poll():
        while not stop.is_set():
            try:
                b = open(p, 'rb').read()
                if len(b) < full // 2 or not b.startswith(b'3D Geometry File Format'): bad.append(('shape', len(b)))
                else: seen.add(len(b))
            except FileNotFoundError: bad.append('missing')
    t = threading.Thread(target=poll); t.start()
    try:
        for i in range(8): write.rename_layer(p, 'brep' if i == 0 else 'N%d' % (i - 1), 'N%d' % i)
    finally: stop.set(); t.join()
    assert not bad, bad[:5]
    assert R.File3dm.Read(p).Layers[0].Name == 'N7'
