"""Fallback tessellation for brep faces without a stored render mesh.
Planar faces: ear clipping of the outer loop (faces with holes are refused).
Untrimmed 4-sided faces: surface grid. Everything else returns None (caller draws edges)."""
import numpy as np

def _area_normal(P):
    n = np.zeros(3)
    for i in range(len(P)): n += np.cross(P[i], P[(i + 1) % len(P)])
    return n

def ear_clip(P):
    """P Nx3 coplanar closed polygon (no repeated end point) -> triangles (M,3) of indices, or None"""
    n = _area_normal(P); l = np.linalg.norm(n)
    if len(P) < 3 or l < 1e-12: return None
    n /= l; a = np.argmax(np.abs(n)); ax = [i for i in range(3) if i != a]
    Q = P[:, ax] * (1 if n[a] > 0 else 1)
    if n[a] < 0: Q = Q[:, ::-1] if False else Q  # orientation handled via signed area below
    def sa(idx): return sum(Q[idx[i], 0] * Q[idx[(i + 1) % len(idx)], 1] - Q[idx[(i + 1) % len(idx)], 0] * Q[idx[i], 1] for i in range(len(idx)))
    idx = list(range(len(P)))
    if sa(idx) < 0: idx.reverse()
    def cross(a_, b_, c_): return (Q[b_, 0] - Q[a_, 0]) * (Q[c_, 1] - Q[a_, 1]) - (Q[b_, 1] - Q[a_, 1]) * (Q[c_, 0] - Q[a_, 0])
    def inside(p, a_, b_, c_):
        return cross(a_, b_, p) >= 0 and cross(b_, c_, p) >= 0 and cross(c_, a_, p) >= 0
    tris = []; guard = 0
    while len(idx) > 3 and guard < 10 * len(P) ** 2:
        guard += 1; clipped = False
        for k in range(len(idx)):
            i0, i1, i2 = idx[k - 1], idx[k], idx[(k + 1) % len(idx)]
            if cross(i0, i1, i2) <= 1e-14: continue
            if any(inside(p, i0, i1, i2) for p in idx if p not in (i0, i1, i2) and not np.allclose(Q[p], Q[i0]) and not np.allclose(Q[p], Q[i1]) and not np.allclose(Q[p], Q[i2])): continue
            tris.append((i0, i1, i2)); del idx[k]; clipped = True; break
        if not clipped: return None
    if len(idx) == 3: tris.append(tuple(idx))
    return np.array(tris, np.int64)

def grid(face, nu=16, nv=16):
    """sample the untrimmed surface of a face; returns (verts, tris)"""
    du, dv = face.Domain(0), face.Domain(1)
    pts = []
    for j in range(nv + 1):
        for i in range(nu + 1):
            p = face.PointAt(du.T0 + (du.T1 - du.T0) * i / nu, dv.T0 + (dv.T1 - dv.T0) * j / nv)
            pts.append((p.X, p.Y, p.Z))
    t = []
    for j in range(nv):
        for i in range(nu):
            a = j * (nu + 1) + i; b = a + 1; c = a + nu + 1; d = c + 1
            t += [(a, b, d), (a, d, c)]
    return np.array(pts, float), np.array(t, np.int64)

def _loop_poly(brep, loop, n=24):
    pts = []
    for t in loop.Trims:
        e = brep.Edges[t.EdgeIndex]; d = e.Domain
        k = 2 if e.IsLinear() else max(2, n * max(1, e.SpanCount))
        s = [e.PointAt(d.T0 + (d.T1 - d.T0) * i / (k - 1)) for i in range(k)]
        s = [(p.X, p.Y, p.Z) for p in s]
        if t.IsReversed: s.reverse()
        pts += s[:-1]
    return np.array(pts, float)

def tess_face(brep, face):
    """-> (verts, tris) or None"""
    loops = list(face.Loops)
    if len(loops) != 1: return None
    L = face.OuterLoop; P = _loop_poly(brep, L)
    if len(P) < 3: return None
    if face.IsPlanar():
        t = ear_clip(P)
        return None if t is None or len(t) == 0 else (P, t)
    if L.TrimCount == 4:
        du, dv = face.Domain(0), face.Domain(1)
        corners = [face.PointAt(u, v) for u in (du.T0, du.T1) for v in (dv.T0, dv.T1)]
        if all(np.min(np.linalg.norm(P - np.array([c.X, c.Y, c.Z]), axis=1)) < 1e-6 * max(1.0, np.ptp(P))
               for c in corners):
            return grid(face)
    return None
