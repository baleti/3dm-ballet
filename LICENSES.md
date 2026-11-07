# Licenses of dependencies and test data

| Item | Use | License | Checked |
|---|---|---|---|
| rhino3dm 8.35.0 (PyPI, wraps openNURBS) | runtime dependency (read, later write) | MIT (package metadata and LICENSE file, McNeel) | 2026-11-07 |
| openNURBS (statically inside rhino3dm) | file format library | openNURBS license: permissive, zlib-like "as is" text, redistribution allowed; bundled zlib (zlib license) | 2026-11-07, text at github.com/mcneel/opennurbs LICENSE |
| numpy | runtime dependency | BSD-3-Clause | |
| pytest | test only | MIT | |
| tests/data/*.3dm | test samples | official `example_files` of github.com/mcneel/opennurbs (V1..V8), files under 150 KB only, shipped under the openNURBS license | 2026-11-07 |

No proprietary SDK bytes are committed. Dependencies are installed with
`pip install --target .deps rhino3dm numpy pytest` (the `.deps` dir is git-ignored).
User/client .3dm files are never committed; keep them outside the repo or under `private/` (ignored).
