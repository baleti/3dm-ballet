# Guarded save (.3dm in place)

Status: experimental, default OFF. The CLI `3dm-ballet rename-layer FILE OLD NEW` is a dry run on a temp copy;
only `--overwrite` replaces the file. Nothing here has been judged by Rhino itself yet (no Rhino available on the
test hosts); the evidence is structural and semantic comparison on public sample files only.

rhino3dm re-serialises the whole file, so identity is not byte level. The save is accepted only when ALL of these hold:

1. Source is a regular file, not a symlink target swap, not hard linked, readable by a memory-capped child probe.
2. An exclusive lock file `FILE.3dmballet.lock` is taken (stale after 10 minutes).
3. Gate: archive version 50/60/70/80 only (older versions are refused), no unreadable objects.
4. The edit is applied, written to a temp file next to the source (`.3dmballet-*.tmp`), re-probed and re-read.
5. Semantic snapshot (taken BEFORE Write, because Write mutates RDK state) of objects, geometry fingerprints,
   attributes, layers, materials, groups, linetypes, bitmaps, dim styles, units/tolerances, views, plug-in data and
   RDK XML (attribute order ignored) must differ only in what the caller expects.
6. Chunk census: records per (table, typecode) in the source must not drop in the output; bytes after the EOF chunk
   count as data that would be lost. (Unknown records are refused because the library drops them.)
7. Source must be unchanged (size, mtime, sha256) since the start of the edit.
8. A backup is written first and never overwritten (`.bak`, `.bak.1`, ...), file mode is kept, the temp file is
   fsynced, then `os.replace`.

Refusal always leaves the original byte-identical. Known lossy public samples (kept as regression files):
`V5-v5_example_file` (annotation geometry, a light/table record), `V5-v5_extrusions` (legacy RDK XML upgraded),
`V7-v7_rhino_logo_annotations` (opaque plug-in data block dropped).

Measured on the public samples (real layer rename): 50 accepted and verified, 56 refused (53 archive versions below
V5, 3 known lossy), 0 damaged. Hard kill mid-save and before the replace leaves the original identical.

Not covered: Rhino itself opening the result, files above V8, document user text keys/values (not exposed by rhino3dm,
only counts compared), Windows/macOS runs.
