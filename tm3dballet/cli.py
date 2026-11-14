"""3dm-ballet FILE.3dm [--no-browser] | info FILE | convert FILE [OUT.glb]"""
import json, os, sys, tempfile, webbrowser
from . import reader, probe

def find_three():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for c in (os.environ.get('THREE_DIR'), os.path.join(here, 'web', 'three'), os.path.join(os.path.dirname(here), 'rvt-ballet', 'web', 'vendor', 'three')):
        if c and os.path.isfile(os.path.join(c, 'three.module.js')): return c

def serve(glbpath, nobrowser=False):
    import http.server, functools, threading
    three = find_three()
    if not three: print('three.js not found: set THREE_DIR to a folder with three.module.js (MIT), or place rvt-ballet next to this repo'); return 2
    page = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web', 'index.html')
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(s):
            u = s.path.split('?')[0]
            if u == '/': f = page
            elif u == '/model.glb': f = glbpath
            elif u.startswith('/three/') and '..' not in u: f = os.path.join(three, u[7:])
            else: s.send_error(404); return
            if not os.path.isfile(f): s.send_error(404); return
            b = open(f, 'rb').read()
            s.send_response(200); s.send_header('Content-Type', 'text/html' if f.endswith('.html') else 'text/javascript' if f.endswith('.js') else 'model/gltf-binary'); s.send_header('Content-Length', str(len(b))); s.end_headers(); s.wfile.write(b)
        def log_message(s, *x): pass
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), H); url = 'http://127.0.0.1:%d/' % srv.server_address[1]
    print(url, flush=True)
    if not nobrowser: webbrowser.open(url)
    try: srv.serve_forever()
    except KeyboardInterrupt: pass
    return 0

def main(argv=None):
    try: return _main(argv)
    except (OSError, probe.Unreadable) as e: print('ERROR: %s' % e); return 1

def _main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    if not a or a[0] in ('-h', '--help'): print(__doc__); return 0
    if a[0] in ('info', 'convert') and len(a) < 2: print('usage: %s FILE.3dm' % a[0]); return 2
    if a[0] == 'info': print(json.dumps(reader.info(a[1]), indent=1)); return 0
    if a[0] == 'convert':
        out = a[2] if len(a) > 2 else os.path.splitext(a[1])[0] + '.glb'
        print(json.dumps(reader.to_glb(a[1], out))); print(out); return 0
    if a[0] == 'rename-layer':
        # rename-layer FILE OLD NEW [--overwrite]: without --overwrite the guarded edit runs on a temp copy only (dry run)
        from . import write
        if len(a) < 4: print('usage: rename-layer FILE OLD NEW [--overwrite]\n  OLD is the layer name, or the full path Parent::Child when several layers share a name'); return 2
        f, old, new = a[1], a[2], a[3]; real = '--overwrite' in a
        target = f
        if not real:
            import shutil
            target = os.path.join(tempfile.mkdtemp(prefix='3dmb-dry-'), os.path.basename(f)); shutil.copyfile(f, target)
        try: ds = write.rename_layer(target, old, new)
        except write.Refused as e: print('REFUSED, file untouched: %s' % e); return 1
        print(('SAVED in place (backup %s.bak*): ' % f if real else 'dry run OK, nothing written (use --overwrite): ') + ', '.join(ds)); return 0
    if a[0] == 'restore-backup':
        from . import write
        if len(a) < 2: print('usage: restore-backup FILE   (puts the newest FILE.bak* back; the current file is kept as a new backup)'); return 2
        try: src, kept = write.restore_backup(a[1])
        except write.Refused as e: print('REFUSED, file untouched: %s' % e); return 1
        print('RESTORED from %s (previous file kept as %s)' % (src, kept)); return 0
    f = a[1] if a[0] == 'open' else a[0]
    print(json.dumps(reader.info(f), indent=1))
    out = os.path.join(tempfile.mkdtemp(prefix='3dmb-'), os.path.basename(f) + '.glb')
    print(json.dumps(reader.to_glb(f, out))); print('glb:', out)
    return serve(out, '--no-browser' in a)

if __name__ == '__main__': sys.exit(main())
