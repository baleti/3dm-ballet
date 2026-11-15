import os, shutil, subprocess, sys, textwrap, pytest
D = os.path.join(os.path.dirname(__file__), 'data')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

@pytest.mark.skipif(os.name != 'posix', reason='rlimit')
@pytest.mark.parametrize('limit', [1000, 8000, 12000])
def test_write_failure_midway_leaves_original_intact(limit, tmp_path):
    """RLIMIT_FSIZE makes writes fail like a full disk: original must be untouched and no tmp left."""
    p = str(tmp_path / 'a.3dm'); shutil.copy(os.path.join(D, 'V7-v7_my_brep.3dm'), p); before = open(p, 'rb').read()
    code = textwrap.dedent('''
        import resource, signal, sys
        from tm3dballet import write
        signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
        resource.setrlimit(resource.RLIMIT_FSIZE, (%d, %d))
        try: write.rename_layer(sys.argv[1], 'brep', 'Renamed'); print('SAVED')
        except Exception as e: print(type(e).__name__)
    ''' % (limit, limit))
    r = subprocess.run([sys.executable, '-c', code, p], capture_output=True, text=True, cwd=ROOT,
                       env=dict(os.environ, PYTHONPATH=os.path.join(ROOT, '.deps') + ':' + ROOT))
    assert 'SAVED' not in r.stdout, r.stdout + r.stderr
    assert open(p, 'rb').read() == before
    assert sorted(os.listdir(tmp_path)) == ['a.3dm'], os.listdir(tmp_path)
