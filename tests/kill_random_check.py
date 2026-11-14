# item 161: manual stress, python3 tests/kill_random_check.py RUNS POINTS : SIGKILL the saving process at a random time, verify the original is
# byte-identical or fully replaced (valid, new name), never partial; stray tmp/lock files are reported (stale lock is expected and handled by the next save)
import sys, os, time, random, shutil, subprocess, tempfile
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path[:0] = [root, os.path.join(root, '.deps')]
import rhino3dm as R
from tm3dballet import write
runs, n = int(sys.argv[1]), int(sys.argv[2])
m = R.File3dm(); L = R.Layer(); L.Name = 'A'; m.Layers.Add(L); pc = R.PointCloud()
for i in range(n): pc.Add(R.Point3d(i, i * .5, -i))
m.Objects.AddPointCloud(pc); d0 = tempfile.mkdtemp(); src = os.path.join(d0, 'src.3dm'); m.Write(src, 7); orig = open(src, 'rb').read()
code = 'import sys\nsys.path[:0]=[%r,%r]\nfrom tm3dballet import write\nwrite.rename_layer(sys.argv[1],"A","B")\n' % (root, os.path.join(root, '.deps'))
res = {'identical': 0, 'replaced_ok': 0, 'BAD': 0}; stale = 0; random.seed(int(sys.argv[3]) if len(sys.argv) > 3 else 1)
t0 = time.time(); probe = tempfile.mkdtemp(); shutil.copy(src, probe + '/a.3dm'); subprocess.run([sys.executable, '-c', code, probe + '/a.3dm']); full = time.time() - t0; shutil.rmtree(probe)
for r in range(runs):
    d = tempfile.mkdtemp(); f = os.path.join(d, 'a.3dm'); shutil.copy(src, f)
    p = subprocess.Popen([sys.executable, '-c', code, f]); time.sleep(random.uniform(0, full * 1.05)); p.kill(); p.wait()
    b = open(f, 'rb').read()
    if b == orig: res['identical'] += 1
    else:
        try: ok = [l.Name for l in R.File3dm.Read(f).Layers] == ['B'] and not write.structure_problem(f)
        except Exception: ok = False
        res['replaced_ok' if ok else 'BAD'] += 1
        if not ok: print('BAD at run', r, 'dir kept', d)
    left = [x for x in os.listdir(d) if x.endswith(('.tmp', '.lock'))]; stale += bool(left)
    if res['BAD'] == 0: shutil.rmtree(d)
    # a stale lock must not block the next save beyond its age; tmp leftovers are cleaned by the next save
print(res, 'runs with leftover tmp/lock after kill:', stale, 'full save secs', round(full, 1))
