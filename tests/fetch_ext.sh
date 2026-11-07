#!/bin/sh
# fetch extra public samples (MIT, mcneel/rhino3dm) into tests/data_ext; not committed
cd "$(dirname "$0")" && mkdir -p data_ext && cd data_ext
B=https://raw.githubusercontent.com/mcneel/rhino3dm/HEAD
for f in blocks groups light mesh meshWithTexture object_UserStrings sphereDecals subd subdBox subd_creases textEntities_r8; do
  [ -f "rh_$f.3dm" ] || curl -sfLo "rh_$f.3dm" "$B/tests/models/$f.3dm"; done
for f in AllMeshModifiers MeshBox_r5 RenderContent Rhino_Logo_Mesh7 decal_r8 nurbsSurface_r5 nurbscurve nurbssurface unassignedmaterials; do
  [ -f "rh_$f.3dm" ] || curl -sfLo "rh_$f.3dm" "$B/docs/__none__" || curl -sfLo "rh_$f.3dm" "https://raw.githubusercontent.com/mcneel/rhino-developer-samples/HEAD/rhino3dm/models/$f.3dm"; done
