"""Byte-flip fuzz: reader and write gate must never crash the process or accept a changed file silently.
Each case runs in a subprocess (native crashes must be contained). Usage: python3 tests/fuzz_3dm.py [N]"""
import os, struct, random, subprocess, sys, tempfile, glob
HERE = os.path.dirname(os.path.abspath(__file__))
CHILD = r'''
import sys
sys.path[:0] = sys.argv[2:]
from tm3dballet import reader, write
import rhino3dm as R
f = sys.argv[1]
try:
    from tm3dballet import probe
    try: probe.probe(f, timeout=15)
    except probe.Unreadable: print('guarded'); sys.exit(0)
    m = R.File3dm.Read(f)
    if m is None: print("none"); sys.exit(0)
    reader.info(f); reader.to_glb(f, f + ".glb")
    print("gate:" + ";".join(write.gate(m)) if write.gate(m) else "ok")
    import hashlib, os
    h0 = hashlib.sha256(open(f, "rb").read()).hexdigest()
    try:
        ds = write.edit_file(f, lambda mm: None, lambda d: d == [])
        print("write:applied" if hashlib.sha256(open(f, "rb").read()).hexdigest() != h0 or ds == [] else "ESCAPE")
    except write.Refused:
        print("write:refused" if hashlib.sha256(open(f, "rb").read()).hexdigest() == h0 else "ESCAPE:original damaged")
    if os.path.exists(f + ".bak") and open(f + ".bak", "rb").read() and hashlib.sha256(open(f + ".bak", "rb").read()).hexdigest() != h0:
        print("ESCAPE:bad backup")
except Exception as e:
    print("exc:" + type(e).__name__)
'''
def chunks(b):
    o, out = 32, []
    while o + 12 <= len(b):
        t, l = struct.unpack_from('<Iq', b, o)
        if l < 0 or o + 12 + l > len(b): break
        out.append((o, l)); o += 12 + l
    return out

def mutate_chunk(b, rnd):
    cs = chunks(b)
    if not cs: return b
    o, l = rnd.choice(cs)
    if rnd.random() < .5: struct.pack_into('<q', b, o + 4, max(0, l + rnd.choice([-8, -1, 1, 8, 1 << 20, -(1 << 40)])))
    else: struct.pack_into('<I', b, o, struct.unpack_from('<I', b, o)[0] ^ (1 << rnd.randrange(32)))
    return b

def run(n=40, seed=1):
    rnd = random.Random(seed); files = sorted(glob.glob(os.path.join(HERE, 'data', 'V[5-8]*.3dm')))
    res = {}
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([os.path.join(HERE, '..'), os.path.join(HERE, '..', '.deps')]))
    for i in range(n):
        src = rnd.choice(files); b = bytearray(open(src, 'rb').read())
        mode = rnd.choice(['flip', 'trunc', 'zero', 'chunk', 'chunk'])
        if mode == 'flip':
            for _ in range(rnd.randint(1, 8)): b[rnd.randrange(len(b))] ^= 1 << rnd.randrange(8)
        elif mode == 'chunk': b = mutate_chunk(b, rnd)
        elif mode == 'trunc': b = b[:rnd.randrange(32, len(b))]
        else:
            p = rnd.randrange(len(b)); b[p:p + 64] = bytes(len(b[p:p + 64]))
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, 'x.3dm'); open(f, 'wb').write(b)
            try: r = subprocess.run([sys.executable, '-I', '-c', CHILD, f, os.path.join(HERE, '..'), os.path.join(HERE, '..', '.deps')], capture_output=True, text=True, timeout=40, env=env)
            except subprocess.TimeoutExpired: k = 'TIMEOUT'
            else: k = 'CRASH rc=%d' % r.returncode if r.returncode else ('ESCAPE' if 'ESCAPE' in r.stdout else (r.stdout.strip().split('\n')[-1] or 'silent'))
        res[(os.path.basename(src), mode, i)] = k
    return res
if __name__ == '__main__':
    res = run(int(sys.argv[1]) if len(sys.argv) > 1 else 40)
    from collections import Counter
    print(Counter(v for v in res.values()))
    bad = {k: v for k, v in res.items() if v.startswith(('CRASH', 'ESCAPE'))}
    for k, v in bad.items(): print(k, v)
    sys.exit(1 if bad else 0)
