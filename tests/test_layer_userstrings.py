import os, pytest
import rhino3dm as R
from tm3dballet import write

def _make(path):
    m = R.File3dm(); l = R.Layer(); l.Name = 'L0'; l.SetUserString('k1', 'v1'); l.SetUserString('uni', 'café 中文'); m.Layers.Add(l)
    c = R.Layer(); c.Name = 'child'; c.ParentLayerId = m.Layers[0].Id; c.SetUserString('c', 'x'); m.Layers.Add(c)
    a = R.ObjectAttributes(); a.SetUserString('obj', 'val'); a.Name = 'pt'
    m.Objects.AddPoint(R.Point3d(1, 2, 3), a)
    assert m.Write(path, 7)

def test_userstrings_survive_rename(tmp_path):
    p = str(tmp_path / 'a.3dm'); _make(p); orig = open(p, 'rb').read()
    s0 = R.File3dm.Read(p)
    us = lambda m: ([sorted(l.GetUserStrings()) for l in m.Layers], [sorted(o.Attributes.GetUserStrings()) for o in m.Objects])
    before = us(s0)
    write.rename_layer(p, 'L0', 'Renamed')
    m = R.File3dm.Read(p)
    assert m.Layers[0].Name == 'Renamed' and m.Layers[1].Name == 'child' and str(m.Layers[1].ParentLayerId) == str(m.Layers[0].Id)
    assert us(m) == before and m.Layers[0].GetUserString('uni') == 'café 中文'
    assert open(p + '.bak', 'rb').read() == orig
