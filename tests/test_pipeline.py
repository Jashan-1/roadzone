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


def _cells(cells, fam, prev=()):
    return {c: {"lat": 37.3, "lon": -122.0, "corridor": {"family_key": list(fam), "prev_family": list(prev)}} for c in cells}


def test_merge_small_folds_into_most_touching_neighbour_and_follows_chains():
    import h3
    from zonegen.pipeline import merge_small
    hub = h3.latlng_to_cell(37.3, -122.0, 8)
    ring = sorted(h3.grid_ring(hub, 1))
    far = h3.latlng_to_cell(36.0, -120.0, 8)
    cells = {**_cells([hub, *ring[:4]], ("I 280", "N")), **_cells(ring[4:], ("CA 92", "E")), **_cells([far], ("CA 1", "S"))}
    assert merge_small(cells, 0) == {}
    cells[far].update(lat=36.0, lon=-120.0)
    assert merge_small(cells, 3) == {("CA 1", "S"): ("I 280", "N"), ("CA 92", "E"): ("I 280", "N")}  # far one: nearest
    near = sorted(h3.grid_ring(hub, 2))[0]
    chain = {**cells, **_cells([near], ("CA 84", "E"))}
    assert set(merge_small(chain, 3).values()) == {("I 280", "N")}
    # road logic beats touching: it sits against I 280 but is reached through US 101
    edge = sorted(h3.grid_ring(hub, 3))
    road = {**_cells([hub, *ring], ("I 280", "N")), **_cells(edge[:10], ("US 101", "N")),
            **_cells([ring_cell for ring_cell in sorted(h3.grid_ring(hub, 2))[:2]], ("CA 1", "N"), ("US 101", "N"))}
    assert merge_small(road, 3) == {("CA 1", "N"): ("US 101", "N")}
    # but not across a gap: the road it arrives on doesn't touch it, so the touching neighbour wins
    apart = {**_cells([hub, *ring], ("I 280", "N")), **_cells([far, *h3.grid_ring(far, 1)], ("US 101", "N")),
             **_cells(sorted(h3.grid_ring(hub, 2))[:2], ("CA 92", "E"), ("US 101", "N"))}
    assert merge_small(apart, 3) == {("CA 92", "E"): ("I 280", "N")}


def test_branch_parents_need_a_majority_and_a_bigger_parent():
    from zonegen.pipeline import branch_parents
    main, side, sub = ("I 280", "N"), ("CA 92", "E"), ("CA 84", "E")
    cells = {**_cells([f"m{i}" for i in range(9)], main), **_cells([f"s{i}" for i in range(4)], side, main),
             **_cells(["x"], side), **_cells(["p", "q"], sub, side)}
    assert branch_parents(cells, {}) == {side: main, sub: main}  # flattened to the main corridor
    half = {**_cells(["a", "b"], main), **_cells(["c"], side, main), **_cells(["d"], side)}
    assert branch_parents(half, {}) == {}
    us, inter = ("US 101", "N"), ("I 880", "N")
    outranks = {**_cells([f"u{i}" for i in range(5)], us), **_cells(["i1", "i2"], inter, us)}
    assert branch_parents(outranks, {}) == {}  # an Interstate is never a branch of a US route


def test_letters_are_clockwise_branches_extend_their_parent_and_the_registry_wins():
    from zonegen.pipeline import _family_letters
    cfg = {"base": {"lat": 37.0, "lon": -122.0}}
    def rec(fam, lat, lon):
        return {"lat": lat, "lon": lon, "corridor": {"family_key": list(fam)}}
    north, east, side, tiny = ("I 280", "N"), ("US 101", "E"), ("CA 92", "N"), ("CA 1", "E")
    recs = [rec(north, 37.5, -122.0), rec(side, 37.5, -121.9), rec(east, 37.0, -121.5), rec(tiny, 37.0, -121.4)]
    registry = {}
    letters = _family_letters(cfg, recs, {tiny: east}, {side: north}, registry)
    assert letters == {north: "A", east: "B", side: "AA", tiny: "B"}
    # a new corridor north of everything can't take A: existing corridors keep their letters
    new = ("CA 17", "N")
    again = _family_letters(cfg, [rec(new, 37.5, -122.1), *recs], {tiny: east}, {side: north}, registry)
    assert again[north] == "A" and again[east] == "B" and again[new] == "C"


def test_letter_overflow_stays_unlike_branches_and_skips_reserved_codes():
    from zonegen.pipeline import _family_letters
    cfg = {"base": {"lat": 37.0, "lon": -122.0}}
    fams = [(f"CA {i}", "N") for i in range(30)]
    recs = [{"lat": 37.5, "lon": -122.0, "corridor": {"family_key": list(f)}} for f in fams]
    codes = set(_family_letters(cfg, recs).values())
    assert len(codes) == 30 and {"Z", "A2", "E2"} <= codes and not any(len(c) == 2 and c.isalpha() for c in codes)
    c = ("CA 87", "S")
    kids = [(f"CA {i}", "S") for i in range(2)]
    recs = [{"lat": 37.5, "lon": -122.0 + i * 0.01, "corridor": {"family_key": list(f)}}
            for i, f in enumerate([("I 5", "N"), ("I 8", "N"), c, *kids])]
    assert _family_letters(cfg, recs, {}, {k: c for k in kids})[kids[0]] == "CB"  # CA is skipped


def test_letters_file_ignores_tiny_base_differences_but_not_the_highway_choice():
    from zonegen.pipeline import letters_path
    a = {"base": {"lat": 37.37078, "lon": -122.04434}, "highway_types": ["I", "US"]}
    near = {"base": {"lat": 37.370784, "lon": -122.044341}, "highway_types": ["I", "US"]}
    assert letters_path(a) == letters_path(near)
    assert letters_path(a) != letters_path({**a, "highway_types": ["I"]})
