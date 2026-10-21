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


def test_signed_direction_prefers_relation_tag_over_forward_role():
    from zonegen.refs import signed_direction
    assert signed_direction("forward", "north") == "north"  # directional relation, one-way member
    assert signed_direction("forward", "") is None  # undirected relation: no signed information
    assert signed_direction("", "S") == "south"  # abbreviated tag
    assert signed_direction("west", "") == "west"  # older style: cardinal member role
    assert signed_direction("backward", "Northbound") is None


def test_fork_candidates_need_two_branches_of_ten():
    from zonegen.pipeline import fork_candidates
    def cell(i, nxt):
        return f"c{i}", {"status": "centroid_sampled", "corridor": {"status": "supported", "family_key": ["I 680", "N"],
                                                                     "next_refs": nxt}}
    cells = dict([cell(i, ["I 580"]) for i in range(12)] + [cell(100 + i, []) for i in range(10)]
                 + [cell(200 + i, ["CA 84"]) for i in range(9)])  # 9 cells: too small to count as a branch
    assert fork_candidates(cells) == [{"family": "I 680 | N", "branches": {"I 580": 12, "stays local": 10},
                                       "cross_branch_test": "not evaluated (M2)"}]
