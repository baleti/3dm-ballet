import os, time, rhino3dm as R, pytest
from tm3dballet import write

def build(tmp_path, nl, npts):
    m = R.File3dm()
    for i in range(nl):
        l = R.Layer(); l.Name = 'L%05d' % i; m.Layers.Add(l)
    for i in range(npts): m.Objects.AddPoint(R.Point3d(i, i % 7, 0))
    p = str(tmp_path / 'a.3dm'); assert m.Write(p, 7); return p

def test_2000_layers(tmp_path):
    p = build(tmp_path, 2000, 10); t = time.time()
    write.rename_layer(p, 'L01000', 'Renamed')
    dt = time.time() - t; names = [l.Name for l in R.File3dm.Read(p).Layers]
    assert len(names) == 2000 and names[1000] == 'Renamed'
    assert dt < 900, dt   # generous: host load; trend is measured by hand
    print('2000 layers save s', round(dt, 1))

def test_20k_points(tmp_path):
    p = build(tmp_path, 3, 20000); n0 = os.path.getsize(p); t = time.time()
    write.rename_layer(p, 'L00001', 'Renamed')
    dt = time.time() - t; m = R.File3dm.Read(p)
    assert len(m.Objects) == 20000 and m.Layers[1].Name == 'Renamed'
    assert dt < 1800, dt
    print('20k points save s', round(dt, 1), 'bytes', n0, os.path.getsize(p))
