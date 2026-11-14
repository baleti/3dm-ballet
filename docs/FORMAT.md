# .3dm format notes and plan

## Known (public)
- The openNURBS file format is documented by the open source openNURBS toolkit (McNeel, permissive license) and the
  "3dm file format" overview. A file is: 32-byte ASCII header "3D Geometry File Format ..." + archive version, then a
  chunk stream (typed chunks with lengths, CRCs per chunk since v2). Tables: properties, settings, bitmaps, materials,
  linetypes, layers, groups, fonts, dimstyles, lights, hatch patterns, instance definitions, objects (geometry +
  attributes), history, user tables, end mark with total length. Archive versions 1,2,3,4,5,50,60,70,80 (V8).
- Geometry classes: point, pointcloud, curves (line, arc, polyline, NURBS, polycurve), surfaces (NURBS, plane, revolution,
  sum), extrusion, brep (with trims), mesh, subd, annotations, hatch, text dot, instance reference, light, clipping plane.
- Breps carry optional render/analysis meshes per face. Rhino stores them in most saved files, but openNURBS example
  files made by code often lack them (observed: samples with Brep and no face mesh draw as wireframe here).
- Units: Settings.ModelUnitSystem; glb output is metres, Y up (x, z, -y), like rvt-ballet.

## Prior art
rhino3dm (MIT, python/js/.NET bindings of openNURBS, read AND write), openNURBS C++ (read/write), three.js 3DMLoader (rhino3dm wasm),
trimesh/assimp do not read 3dm natively. Decision: use rhino3dm for decode; do not reimplement the chunk parser unless a
gap proves it necessary.

## Measured on 86 public openNURBS samples (V1..V8, under 150 KB)
- all open; 880 wire objects, 34 meshed, skipped: point 42, textdot 84, annotation 19, hatch 7, surface 11, light 5, pointset 5.
- rhino3dm load then Write (no edit) succeeds for all 86 and the re-read summary (counts, types, layers) matches, but output is
  NEVER byte-identical to the input (0/86): the writer re-serializes (timestamps, application block, table order). So a
  future in-place save must not use whole-file re-serialization for untouched content without a stronger proof.

## Unknown / to do
- Real-world files (large, V5 to V8, with plug-in user data, SubD, render content, embedded bitmaps) not tested: none are
  available here beyond public samples.
- Brep meshing without stored meshes (needs a tessellator; trims, planar faces). Currently wireframe.
- Instance references (blocks) are not expanded in the glb yet; layers nested visibility; materials colors/transparency.
- Write support plan: (1) object-level edits through rhino3dm (attributes, layer, transform) with archive version preserved;
  (2) round trip check by equivalence (object ids, geometry hash, tables), since byte identity is not available;
  (3) 3-way gate like savegate: refuse on unknown chunks / user-data plug-ins not understood, write temp, re-read, compare,
  atomic replace, keep backup. (4) Final oracle would be Rhino itself (not available offline here).

## Record types to decode first
Mesh, Brep face meshes, Curves (done as wire), Extrusion, InstanceReference (blocks), Layer visibility/colour, Material colour,
then Brep tessellation, SubD, Annotation text.

## Write gate findings (tm3dballet/write.py, 2026-11-07)
- rhino3dm rewrites the whole file; identity is checked by a semantic snapshot (object ids, structural geometry fingerprints,
  attributes, layers, materials, block definitions, plug-in data list, RDK xml) of the input vs the re-read output.
- Archive versions 1 to 4 are refused: writing V2 converts PolyCurve to NurbsCurve (same shape, different representation).
- Source layer table must be consistent (layer_id_problem): a duplicated layer record made the library renumber the duplicate id silently on save (found by byte patching a public V6 sample); each layer id must sit in exactly one layer record and parents must exist. Dangling-parent branch is not yet covered by a byte-patched test (V7 layer record sub-chunk CRCs not mapped).
- Public samples: 33 writable (V5 to V8) plus 20 extra; 2 are caught as lossy (V5 example_file annotation changes, V7
  rhino_logo_annotations drops one opaque plug-in data block). Encode() bytes are NOT canonical (meshes differ although all
  arrays are equal), so meshes and curves use structural fingerprints.
- Not covered by the snapshot yet: user strings/user data, views, render content details, SubD beyond Encode hash. Final oracle
  (Rhino opening the output) is unavailable offline; overwrite of originals must stay off until that exists.

## Robustness findings (2026-11-07)
- rhino3dm `File3dm.Read` can loop forever on corrupt input (found by byte-flip/zero fuzz of V5-V8 samples: 6 of 60 cases).
  All reads therefore go through `tm3dballet/probe.py` (throwaway subprocess, timeout) before any in-process read; hostile
  files are refused, never hang a viewer or a save. Regression file: tests/regress/hang_v7_surfaces_zeroed.3dm.
- Fuzz harness: `python3 tests/fuzz_3dm.py [N]` (each case isolated in a subprocess).
