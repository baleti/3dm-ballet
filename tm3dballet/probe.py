"""Hang/crash guard: rhino3dm's native reader can loop forever on corrupt input, so every file is
first read in a throwaway subprocess with a timeout. Only files that pass are read in-process."""
import subprocess, sys, os

class Unreadable(ValueError):
    pass

_CHILD = ("import sys; sys.path[:0] = sys.argv[2:]\n"
          "import rhino3dm as R\n"
          "m = R.File3dm.Read(sys.argv[1]); sys.exit(0 if m is not None else 3)\n")

_OK = {}   # in-process cache of files that passed: key includes size, mtime_ns and inode so any change re-probes

def _key(path):
    st = os.stat(path)
    return (os.path.realpath(path), st.st_size, st.st_mtime_ns, st.st_ino)

def probe(path, timeout=30):
    try: k = _key(path)
    except OSError as e: raise Unreadable('cannot stat %s: %s' % (path, e))
    if k in _OK: return
    _probe(path, timeout)
    try:
        if _key(path) == k: _OK[k] = True      # only cache if the file did not change while probing
    except OSError: pass

def _probe(path, timeout):
    paths = [p for p in sys.path if p]
    try:
        r = subprocess.run([sys.executable, '-I', '-c', _CHILD, path] + paths, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise Unreadable('reader timed out (corrupt or hostile file): %s' % path)
    if r.returncode != 0:
        raise Unreadable('reader failed (rc=%d): %s' % (r.returncode, path))
