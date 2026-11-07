import glob, numpy as np, pytest
from tm3dballet import tess, reader

def area(P, T):
    return sum(np.linalg.norm(np.cross(P[b] - P[a], P[c] - P[a])) / 2 for a, b, c in T)

def test_ear_clip_concave_L():
    P = np.array([(0, 0, 0), (2, 0, 0), (2, 1, 0), (1, 1, 0), (1, 2, 0), (0, 2, 0)], float)
    for Q in (P, P[::-1]):
        T = tess.ear_clip(Q); assert len(T) == 4 and abs(area(Q, T) - 3) < 1e-9

def test_ear_clip_tilted_plane():
    P = np.array([(0, 0, 0), (2, 0, 2), (2, 3, 2), (0, 3, 0)], float)
    assert abs(area(P, tess.ear_clip(P)) - 2 * 3 * 2 ** .5) < 1e-9

def test_degenerate():
    assert tess.ear_clip(np.array([(0, 0, 0), (1, 0, 0), (2, 0, 0)], float)) is None

def test_brep_samples_now_meshed(tmp_path):
    st = reader.to_glb('tests/data/V2-v2_DeformCubes.3dm', str(tmp_path / 'a.glb'))
    assert st['meshed'] >= 6

def test_points_become_markers(tmp_path):
    st = reader.to_glb('tests/data/V2-v2_23_points.3dm', str(tmp_path / 'p.glb'))
    assert st.get('wire', 0) >= 23 and not any(k.startswith('skipped_Point') for k in st)
