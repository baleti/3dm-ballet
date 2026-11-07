"""3dm-ballet FILE.3dm | info FILE | convert FILE [OUT.glb]"""
import json, os, sys, tempfile, webbrowser
from . import reader

def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    if not a or a[0] in ('-h', '--help'): print(__doc__); return 0
    if a[0] == 'info': print(json.dumps(reader.info(a[1]), indent=1)); return 0
    if a[0] == 'convert':
        out = a[2] if len(a) > 2 else os.path.splitext(a[1])[0] + '.glb'
        print(json.dumps(reader.to_glb(a[1], out))); print(out); return 0
    f = a[1] if a[0] == 'open' else a[0]
    print(json.dumps(reader.info(f), indent=1))
    out = os.path.join(tempfile.mkdtemp(prefix='3dmb-'), os.path.basename(f) + '.glb')
    print(json.dumps(reader.to_glb(f, out))); print('glb:', out)
    print('viewer hookup: serve this glb with the rvt-ballet front-end (see docs/FORMAT.md)')
    return 0

if __name__ == '__main__': sys.exit(main())
