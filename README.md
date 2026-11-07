# 3dm-ballet

Read (and later safely edit) Rhino `.3dm` files. Sibling of rvt-ballet (same glb/Three.js front-end conventions).

```
3dm-ballet FILE.3dm            # print info, write a glb, (viewer hookup pending)
3dm-ballet info FILE.3dm       # JSON: version, units, object types, layers, materials, groups, blocks
3dm-ballet convert FILE.3dm [OUT.glb]
```

Status: minimal reader on top of rhino3dm (MIT, openNURBS). Solids with stored render meshes and mesh objects are
meshed, curves and mesh-less breps are drawn as wireframe, other types are counted and skipped.
See docs/FORMAT.md for what is known/unknown and the write plan, LICENSES.md for dependencies.

Install: `pip install --target .deps rhino3dm numpy pytest`; tests: `PYTHONPATH=.deps python3 -m pytest tests`.
Portable code, no platform-specific paths.
