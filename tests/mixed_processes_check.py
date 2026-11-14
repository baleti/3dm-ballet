# manual: 8 processes (4 rename + 4 restore-backup) on one file, 5 rounds; run from the repo root with rhino3dm in .deps
import sys, os, shutil, subprocess, glob
sys.path.insert(0,'.deps')
import rhino3dm as R
d=__import__('tempfile').mkdtemp(); bad=0
for rnd in range(5):
    shutil.rmtree(d,ignore_errors=True); os.mkdir(d); f=d+'/a.3dm'
    shutil.copy('tests/data/V7-v7_my_brep.3dm',f)
    subprocess.run(['./3dm-ballet','rename-layer',f,'brep','N0','--overwrite'],capture_output=True)
    ps=[]
    for i in range(4):
        ps.append(subprocess.Popen(['./3dm-ballet','rename-layer',f,'N0','M%d'%i,'--overwrite'],stdout=subprocess.PIPE,text=True))
        ps.append(subprocess.Popen(['./3dm-ballet','restore-backup',f],stdout=subprocess.PIPE,text=True))
    outs=[p.communicate()[0].split('\n')[0][:30] for p in ps]
    try: n=[l.Name for l in R.File3dm.Read(f).Layers]
    except Exception as e: n=repr(e); bad+=1
    left=[x for x in os.listdir(d) if x.endswith(('.lock','.tmp'))]
    nb=[x for x in os.listdir(d) if '.bak' in x]
    badbak=[x for x in nb if len(R.File3dm.Read(d+'/'+x).Layers)!=1]
    if left or badbak: bad+=1
    print(rnd,n,len(nb),left,badbak,sum(o.startswith('SAVED') or o.startswith('RESTORED') for o in outs))
print('bad',bad)
