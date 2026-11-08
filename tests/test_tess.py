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


def _sq(x0, y0, s): return np.array([[x0, y0, 0], [x0 + s, y0, 0], [x0 + s, y0 + s, 0], [x0, y0 + s, 0]], float)

def _area(P, T):
    return sum(abs(np.linalg.norm(np.cross(P[b] - P[a], P[c] - P[a]))) / 2 for a, b, c in T)

def test_square_with_hole_area_exact():
    from tm3dballet import tess
    M = tess.merge_holes(_sq(0, 0, 10), [_sq(3, 3, 4)])
    T = tess.ear_clip(M)
    assert T is not None and abs(_area(M, T) - (100 - 16)) < 1e-9

def test_two_holes_and_reversed_orientation():
    from tm3dballet import tess
    outer = _sq(0, 0, 10)[::-1]; holes = [_sq(1, 1, 2), _sq(6, 6, 3)[::-1]]
    M = tess.merge_holes(outer, holes); T = tess.ear_clip(M)
    assert T is not None and abs(_area(M, T) - (100 - 4 - 9)) < 1e-9

def test_tilted_plane_hole():
    from tm3dballet import tess
    R = np.array([[1, 0, 0], [0, .6, -.8], [0, .8, .6]])
    M = tess.merge_holes(_sq(0, 0, 10) @ R.T, [_sq(3, 3, 4) @ R.T]); T = tess.ear_clip(M)
    assert abs(_area(M, T) - 84) < 1e-9


def test_real_planar_faces_with_holes_tessellate():
    import rhino3dm as R, os
    from tm3dballet import tess
    n = ok = 0
    for f in sorted(glob.glob(os.path.join(os.path.dirname(__file__), 'data*', '*.3dm'))):
        m = R.File3dm.Read(f)
        if m is None: continue
        for o in m.Objects:
            g = o.Geometry
            if not isinstance(g, R.Brep): continue
            for fc in g.Faces:
                if len(list(fc.Loops)) > 1 and fc.IsPlanar():
                    n += 1; r = tess.tess_face(g, fc)
                    if r is None: continue
                    ok += 1; P, T = r
                    kinds = [str(l.LoopType).split('.')[-1] for l in fc.Loops]
                    polys = [tess._loop_poly(g, l) for l in fc.Loops]
                    nrm = tess._area_normal(polys[kinds.index('Outer')]); nrm /= np.linalg.norm(nrm)
                    exp = abs(tess._sarea(tess._proj(polys[kinds.index('Outer')], nrm))) - sum(abs(tess._sarea(tess._proj(p, nrm))) for p, k in zip(polys, kinds) if k == 'Inner')
                    sc = 1 / abs(nrm[np.argmax(np.abs(nrm))])
                    assert abs(_area(P, T) - exp * sc) < 1e-2 * max(1e-3, exp * sc)   # planar within model tolerance, not exactly
    assert n >= 5 and ok >= 5
