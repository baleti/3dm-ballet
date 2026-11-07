"""Block (instance) expansion, tested on a mock model because no public sample contains blocks
and rhino3dm cannot author instance definitions."""
import json, struct, types
import numpy as np
from tm3dballet import reader

P = lambda x, y, z: types.SimpleNamespace(X=x, Y=y, Z=z)

class Xf:
    def __init__(self, tx): self.tx = tx
    def ToFloatArray(self, rm): return (1, 0, 0, self.tx, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)

def mesh_obj(oid, mode='Normal'):
    g = types.SimpleNamespace(ObjectType='ObjectType.Mesh', Vertices=[P(0, 0, 0), P(1, 0, 0), P(0, 1, 0)], Faces=[(0, 1, 2, 2)])
    a = types.SimpleNamespace(Visible=True, LayerIndex=0, ColorSource=0, ObjectColor=(0, 0, 0, 255), Id=oid, Mode='ObjectMode.' + mode)
    return types.SimpleNamespace(Geometry=g, Attributes=a)

def inst_obj(oid, idef, tx, mode='Normal'):
    g = types.SimpleNamespace(ObjectType='ObjectType.InstanceReference', ParentIdefId=idef, Xform=Xf(tx))
    a = types.SimpleNamespace(Visible=True, LayerIndex=0, ColorSource=0, ObjectColor=(0, 0, 0, 255), Id=oid, Mode='ObjectMode.' + mode)
    return types.SimpleNamespace(Geometry=g, Attributes=a)

def model(objs, idefs):
    lay = types.SimpleNamespace(Color=(10, 20, 30, 255), Name='L', GetPersistentVisibility=lambda: True)
    return types.SimpleNamespace(Layers=[lay], Objects=objs, InstanceDefinitions=idefs,
                                 Settings=types.SimpleNamespace(ModelUnitSystem='UnitSystem.Meters'))

def glb_x(path):
    b = open(path, 'rb').read(); jl = struct.unpack('<I', b[12:16])[0]
    j = json.loads(b[20:20 + jl]); return [a for a in j['accessors'] if a['type'] == 'VEC3']

def test_nested_instances(tmp_path, monkeypatch):
    d1 = types.SimpleNamespace(Id='D1', GetObjectIds=lambda: ['m1'])
    d2 = types.SimpleNamespace(Id='D2', GetObjectIds=lambda: ['i1', 'i1b'])
    objs = [mesh_obj('m1', 'InstanceDefinitionObject'), inst_obj('i1', 'D1', 10, 'InstanceDefinitionObject'),
            inst_obj('i1b', 'D1', 20, 'InstanceDefinitionObject'), inst_obj('top', 'D2', 100), mesh_obj('loose')]
    monkeypatch.setattr(reader, 'load', lambda p: model(objs, [d1, d2]))
    st = reader.to_glb('x', str(tmp_path / 'o.glb'))
    assert st['idef_member'] == 3 and st['instances'] == 3 and st['meshed'] == 3
    (acc,) = glb_x(tmp_path / 'o.glb')
    assert acc['count'] == 9 and acc['min'][0] == 0 and acc['max'][0] == 121  # 100+20+1

def test_unresolved_and_cycle(tmp_path, monkeypatch):
    d = types.SimpleNamespace(Id='D', GetObjectIds=lambda: ['self'])
    objs = [inst_obj('self', 'D', 1, 'InstanceDefinitionObject'), inst_obj('a', 'D', 0), inst_obj('b', 'MISSING', 0), mesh_obj('m')]
    monkeypatch.setattr(reader, 'load', lambda p: model(objs, [d]))
    st = reader.to_glb('x', str(tmp_path / 'o.glb'))
    assert st['instance_unresolved'] >= 2 and st['meshed'] == 1

def test_parent_layer_hidden(tmp_path, monkeypatch):
    mk = lambda i, par, vis: types.SimpleNamespace(Id=i, ParentLayerId=par, Color=(1, 2, 3, 255), Name=i, GetPersistentVisibility=lambda: vis)
    m = model([mesh_obj('a')], [])
    m.Layers = [mk('c', 'p', True), mk('p', 'z', False), mk('z', '0', True)]
    monkeypatch.setattr(reader, 'load', lambda p: m)
    assert reader.to_glb('x', str(tmp_path / 'o.glb')).get('layer_hidden') == 1
    m.Layers[1] = mk('p', 'c', True)  # parent cycle must terminate and be visible
    assert reader.to_glb('x', str(tmp_path / 'o.glb')).get('meshed') == 1
