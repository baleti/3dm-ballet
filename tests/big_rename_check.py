# item 159: manual stress check, python3 tests/big_rename_check.py N (N points in one point cloud); not collected by pytest
import sys, os, time, shutil, tempfile
sys.path[:0] = [os.path.dirname(os.path.dirname(os.path.abspath(__file__))), os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.deps')]
import rhino3dm as R
from tm3dballet import write
N = int(sys.argv[1])
m = R.File3dm(); L = R.Layer(); L.Name = 'A'; m.Layers.Add(L)
pc = R.PointCloud()
for i in range(N): pc.Add(R.Point3d(i, i * .5, -i))
m.Objects.AddPointCloud(pc)
d = tempfile.mkdtemp(dir=None); f = os.path.join(d, 'big.3dm'); m.Write(f, 7)
sz = os.path.getsize(f); b = open(f, 'rb').read(); t = time.time()
try: r = write.rename_layer(f, 'A', 'B')
except write.Refused as e: r = 'REFUSED ' + str(e)[:100]
print(N, 'size MB', sz // 2**20, 'result', r, 'secs', round(time.time() - t), 'listing', sorted(os.listdir(d)), 'orig identical or replaced ok',
      open(f, 'rb').read() == b or [l.Name for l in R.File3dm.Read(f).Layers] == ['B'])
shutil.rmtree(d)
