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

## Proven so far (public samples only, 106 files: 52 saveable, 54 refused)

Tests: tests/test_write.py (roundtrip, gate, lossy files, kill mid-save, symlink/hardlink/readonly, source swapped
during edit), tests/test_savegate.py, tests/test_geom_after_rename.py (per-object bbox and point/face counts equal
before and after rename on all 52 saveable samples), glb export of source vs output identical (geometry binary
byte-identical on all 52), table chunks (materials, bitmaps, object table) byte-identical after rename and after a
second rename, independent pure-Python chunk CRC walk of every output, stale lock after SIGKILL, write failure
injection (os.replace, fsync, write), CLI dry run on all 106 samples (exit 0 or 1, no traceback).

Limits, NOT proven: no Rhino application oracle (nothing was opened in Rhino), no directory fsync after replace,
archive versions below V5 and above V8 refused, Windows/macOS untested, only layer rename is an edit operation.

CLI exit codes (`rename-layer`): 0 = dry run OK or saved; 1 = refused (gate, missing layer, lock held, hardlink,
read-only directory), message `REFUSED, file untouched: ...` on stdout, source bytes unchanged; 2 = usage error or
missing viewer dependency. Asserted in tests/test_cli.py. Backup names (`.bak`, `.bak.N`) never reuse an existing
sibling file name, tested in tests/test_write.py.

Permissions and times: the permission bits of the original are kept on the saved file (tested for 0644, 0600, 0664,
0755; a read-only 0444 source is either saved with 0444 kept or refused); the saved file gets the save time as mtime;
the backup is made with copy2, so it keeps the source mtime. Ownership is not touched (no chown). A disk-full during
the backup copy removes the partial backup and refuses the save.

Restore: `3dm-ballet restore-backup FILE` copies the newest `FILE.bak*` (highest N) back over FILE through a temp file,
after the backup passes the same probe and structure checks as a source; the replaced file is kept as a new backup so a
restore can be undone. Exit 1 and no change when there is no backup or it is truncated/damaged.

Durability: after os.replace the containing directory is fsynced on posix (best effort, failure ignored; no-op on Windows).

## Additional proofs (queue 131-144)

- Four processes racing renames on one file: every outcome valid, no tmp or lock left.
- Ten chained renames: ten distinct backups, first equals the source, final differs only in layers.
- Odd new names (NUL, control chars, 10k chars, empty, spaces, unicode, `::`): refused with original intact or exact
  read-back; empty and NUL never accepted.
- Odd file names (255 chars refused cleanly because the lock name is too long; dots, unicode, hidden accepted).
- Disk full halfway through the backup copy: save refused, no truncated backup left (bug found and fixed).
- Permissions kept, mtime policy, truncated sources at 11 lengths refused, `restore-backup`, directory fsync.
- All four permanent fuzz/hang regression files, case-only renames, a 2000-layer synthetic file (1 of 2000 layer
  records changes), every non-layer table identical after rename on 52 samples.

Group: the saved file gets the original file's group back (chown to the same gid); when that is not possible (user not a member) the save is refused instead of silently changing the group.

Stale locks: a lock whose pid no longer exists (posix) is cleared at once; otherwise a lock blocks for LOCK_STALE_S (10 min).

## Additional proofs (queue 162-179)

- Temp file always beside the source (TMPDIR on another filesystem is irrelevant); rename racing restore-backup: the lock serializes, file always a valid old or new version.
- `restore-backup` through a symlinked file replaces the target and keeps the link; a symlinked or truncated newest backup is refused with the file untouched.
- Layer names that are not valid Unicode (lone surrogate, which Linux argv produces for invalid UTF-8) are refused cleanly.
- Backup names already taken by a directory or a dangling symlink are skipped; backups are never pruned (one per save, 30 saves = 30 valid backups).
- Bytes after the last chunk (junk or zeros) are refused, since the writer would drop them. FIFO/directory sources refused without hanging.
- A read-only source (no write permission) is refused up front; the flag is never overridden.
- CLI works with spaces, accents and a leading-dash file name given as a path (a bare `--` terminator is not supported).

## Additional proofs (queue 181-199)

- **Temp file re-verified before install:** its sha256 is taken when the gate judges it and re-checked right before the replace; a flipped byte in between refuses the save.
- **Backup verified by content:** the backup copy must hash equal to the source (not only equal size), else the save is refused and the bad backup removed.
- **Installed file verified:** after the replace the installed bytes are re-hashed; on mismatch the original is put back from the verified backup (or the save reports that no backup exists). Limit: this sees what a re-read sees, not a lying disk.
- A one-byte source change with size and mtime restored during the edit is refused.
- 8 processes (4 rename + 4 restore-backup) on one file: lock serializes, file and every backup always valid. SIGSTOP of a saving process holds the lock, a second save is refused.
- SIGKILL during rename (earlier) and during restore-backup (30 runs): file is the old or the new version, never partial.
- RLIMIT_FSIZE below the output size: refused, original intact. ulimit -v 1.5 GB and 4 GB: 45 MB file saves.
- Random bit flips (60 on a V7 sample): 57 refused, 3 saved with backup equal to the damaged source, 0 damaged. Inserted bytes can make the library reader hang; the 30 s probe timeout refuses those files safely.
- 100-deep layer chain, V5/V6 samples (20 of 21 saved, 1 refused), V8 samples, FIFO/directory sources: all safe.
- 218: a new backup always gets a number above every existing FILE.bak.N (stray ones included), so restore-backup picks it.
