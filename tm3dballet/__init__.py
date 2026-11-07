"""3dm-ballet: read Rhino .3dm files (openNURBS via rhino3dm, MIT). Sibling of rvt-ballet."""
import os, sys
_d = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.deps')
if os.path.isdir(_d) and _d not in sys.path: sys.path.append(_d)
