import os, pytest
from tm3dballet import probe, reader, write
HERE = os.path.dirname(os.path.abspath(__file__))
HANG = os.path.join(HERE, 'regress', 'hang_v7_surfaces_zeroed.3dm')

def test_hang_file_rejected_not_hung():
    with pytest.raises(probe.Unreadable): probe.probe(HANG, timeout=5)

def test_reader_load_guarded():
    with pytest.raises(probe.Unreadable): reader.load(HANG)

def test_write_refuses_and_original_untouched(tmp_path):
    f = tmp_path / 'a.3dm'; f.write_bytes(open(HANG, 'rb').read()); before = f.read_bytes()
    with pytest.raises(write.Refused): write.edit_file(str(f), lambda m: None, lambda d: True)
    assert f.read_bytes() == before and not os.path.exists(str(f) + '.bak')

def test_adapter_rejects_hang_bytes():
    from tm3dballet.sgadapter import Dm3Adapter
    a = Dm3Adapter(); buf = open(HANG, 'rb').read()
    assert a.sniff(buf) is None
    with pytest.raises(Exception): a.validate(buf)
