import os, rhino3dm as R, pytest
from tm3dballet import write

def mk(tmp_path):
    m = R.File3dm(); ids = {}
    for n, par in [('P1', None), ('P2', None), ('kid', 'P1'), ('other', 'P2')]:
        l = R.Layer(); l.Name = n
        if par: l.ParentLayerId = ids[par]
        idx = m.Layers.Add(l); ids[n] = m.Layers[idx].Id
    p = str(tmp_path / 'a.3dm'); assert m.Write(p, 7); return p

def tree(p): 
    ls = list(R.File3dm.Read(p).Layers); by = {str(l.Id): l.Name for l in ls}
    return sorted((l.Name, by.get(str(l.ParentLayerId), '-')) for l in ls)

def test_child_takes_name_used_under_other_parent(tmp_path):
    p = mk(tmp_path); before = tree(p)
    write.rename_layer(p, 'P1::kid', 'other')
    assert tree(p) == sorted([('P1', '-'), ('P2', '-'), ('other', 'P1'), ('other', 'P2')]) and before != tree(p)

def test_rename_to_sibling_name_refused_untouched(tmp_path):
    p = mk(tmp_path); orig = open(p, 'rb').read()
    with pytest.raises(write.Refused): write.rename_layer(p, 'P1', 'p2')
    assert open(p, 'rb').read() == orig

def test_parent_rename_keeps_children_attached(tmp_path):
    p = mk(tmp_path); write.rename_layer(p, 'P1', 'Parent')
    assert tree(p) == sorted([('Parent', '-'), ('P2', '-'), ('kid', 'Parent'), ('other', 'P2')])
