from zonegen.classify import band_edges, band_index
from zonegen.pipeline import in_boundary, load_boundary

POLY = """test
1
   -1.0   -1.0
    1.0   -1.0
    1.0    1.0
   -1.0    1.0
END
!2
   -0.1   -0.1
    0.1   -0.1
    0.1    0.1
END
END
"""


def test_boundary_poly_outer_ring_and_missing_config(tmp_path):
    p = tmp_path / "x.poly"
    p.write_text(POLY)
    b = load_boundary(str(p))
    assert in_boundary(b, 0.5, 0.5) and not in_boundary(b, 2.0, 0.0)
    assert in_boundary(None, 99, 99)  # no boundary configured: nothing is excluded


def test_band_edges_drive_band_index():
    edges = band_edges(5, 10, 50)
    assert edges == [5, 15, 25, 35, 45]
    assert [band_index(e, 5, 10, 50) for e in edges] == [1, 2, 3, 4, 5]
