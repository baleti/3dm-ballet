# manual: N random-time SIGKILLs of `3dm-ballet restore-backup`; run from repo root with rhino3dm in .deps; python3 tests/kill_restore_check.py [N]
import sys, os, random, shutil, subprocess, tempfile, time, signal
sys.path[:0] = ['.deps', '.']
import rhino3dm as R
N = int(sys.argv[1]) if len(sys.argv) > 1 else 30
src = 'tests/data/V7-v7_my_brep.3dm'; rnd = random.Random(3); res = {'orig_intact': 0, 'restored': 0, 'BAD': 0}
for i in range(N):
    d = tempfile.mkdtemp(); f = d + '/a.3dm'; shutil.copy(src, f)
    subprocess.run(['./3dm-ballet', 'rename-layer', f, 'brep', 'N', '--overwrite'], capture_output=True)
    cur = open(f, 'rb').read(); old = open(f + '.bak', 'rb').read()
    p = subprocess.Popen(['./3dm-ballet', 'restore-backup', f], stdout=subprocess.DEVNULL)
    time.sleep(rnd.uniform(0, 1.2)); p.send_signal(signal.SIGKILL); p.wait()
    b = open(f, 'rb').read()
    try: ok = len(R.File3dm.Read(f).Layers) == 1
    except Exception: ok = False
    if ok and b == cur: res['orig_intact'] += 1
    elif ok and b == old: res['restored'] += 1
    else: res['BAD'] += 1; print('BAD', i)
    for n in os.listdir(d):
        if '.bak' in n:
            try: assert len(R.File3dm.Read(d + '/' + n).Layers) == 1
            except Exception: res['BAD'] += 1; print('BAD backup', n)
    shutil.rmtree(d)
print(res)
