# manual: N random single-byte flips in a real sample, then rename; python3 tests/flip_fuzz_check.py [N] [sample]; run from repo root with rhino3dm in .deps
import sys, os, random, shutil, tempfile
sys.path[:0] = ['.deps', '.']
import rhino3dm as R
from tm3dballet import write
N = int(sys.argv[1]) if len(sys.argv) > 1 else 200
src = sys.argv[2] if len(sys.argv) > 2 else 'tests/data/V7-v7_my_brep.3dm'
raw = open(src, 'rb').read(); rnd = random.Random(7); d = tempfile.mkdtemp(); f = os.path.join(d, 'a.3dm')
res = {'refused': 0, 'saved_ok': 0, 'BAD': 0}
for i in range(N):
    b = bytearray(raw); pos = rnd.randrange(len(b)); b[pos] ^= 1 << rnd.randrange(8); open(f, 'wb').write(b)
    for e in os.listdir(d):
        if e != 'a.3dm': os.remove(os.path.join(d, e))
    try: lay = R.File3dm.Read(f).Layers[0].Name
    except Exception: lay = None
    if lay is None: lay = 'x'
    try:
        write.rename_layer(f, lay, 'Zq9')
        try: ok = R.File3dm.Read(f).Layers[0].Name == 'Zq9' and open(f + '.bak', 'rb').read() == bytes(b)
        except Exception: ok = False
        res['saved_ok' if ok else 'BAD'] += 1
        if not ok: print('BAD saved', pos)
    except write.Refused:
        if open(f, 'rb').read() != bytes(b) or any(x != 'a.3dm' for x in os.listdir(d)): res['BAD'] += 1; print('BAD refused-but-changed', pos)
        else: res['refused'] += 1
    except Exception as e: res['BAD'] += 1; print('EXC', pos, repr(e)[:80])
print(res)
