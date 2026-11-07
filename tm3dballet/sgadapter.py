"""savegate adapter for .3dm (plug into savegate.open_doc(path, adapter=Dm3Adapter())).
Snapshot keys: 'obj:<id>', one key per table/setting. Gate name: format '3dm', version = 'v<archive>' e.g. v80.
Overwrite of originals stays behind savegate's two gates (Config.allow_overwrite and the oracle gate file)."""
import hashlib, os, tempfile
import rhino3dm as R
from . import write, probe

MAGIC = b'3D Geometry File Format '
WRITABLE = ('v50', 'v60', 'v70', 'v80')

def _model(buf):
    import os, tempfile
    fd, tmp = tempfile.mkstemp(suffix='.3dm'); os.close(fd)
    try:
        open(tmp, 'wb').write(bytes(buf)); probe.probe(tmp)
    finally:
        os.unlink(tmp)
    m = R.File3dm.FromByteArray(bytes(buf))
    if m is None: raise ValueError('unreadable 3dm')
    return m

def _flat(m):
    s = write.snapshot(m); out = {'obj:' + k: repr(sorted(v.items())) for k, v in s['objects'].items()}
    for k, v in s.items():
        if k != 'objects': out[k] = repr(v)
    return out

class Dm3Adapter:
    name = '3dm'
    def sniff(self, buf):
        if bytes(buf[:24]) != MAGIC: return None
        try: v = _model(buf).ArchiveVersion
        except Exception: return None
        return 'v%d' % v
    def snapshot(self, buf): return _flat(_model(buf))
    def validate(self, buf):
        m = _model(buf); why = write.gate(m)
        if why: raise ValueError('; '.join(why))
        return 'ok'

def serialize(model):
    """model -> bytes at its own archive version (rhino3dm has no in-memory writer, so via a temp file)"""
    fd, tmp = tempfile.mkstemp(suffix='.3dm'); os.close(fd)
    try:
        if not model.Write(tmp, model.ArchiveVersion): raise ValueError('write failed')
        return open(tmp, 'rb').read()
    finally:
        os.remove(tmp)
