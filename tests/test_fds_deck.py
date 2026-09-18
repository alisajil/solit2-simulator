from solit2.engines.fds import deck
from solit2.schema.design import Design

BASELINE = "designs/og-dbr-rev0.json"
TEST_RIG = "examples/designs/solit2-test-protocol.json"


def test_the_deck_opens_with_head_and_closes_with_tail():
    text = deck.generate(Design.load(BASELINE))
    assert text.startswith("&HEAD")
    assert text.rstrip().endswith("&TAIL /")


def test_the_deck_is_deterministic():
    design = Design.load(BASELINE)
    assert deck.generate(design) == deck.generate(design)


def test_the_chid_is_the_design_sha():
    from solit2.engines.reduced.envelope import _design_sha
    design = Design.load(BASELINE)
    assert f"CHID='{_design_sha(design)}'" in deck.generate(design)


def test_the_domain_holds_every_station_the_criteria_read():
    from solit2.engines.reduced.criteria import STATIONS
    text = deck.generate(Design.load(BASELINE))
    mesh_lines = [ln for ln in text.splitlines() if ln.startswith("&MESH")]
    assert len(mesh_lines) == 3, "far upstream, core, far downstream"
    assert str(deck.WINDOW_M[0]) in mesh_lines[0]
    assert str(deck.WINDOW_M[1]) in mesh_lines[-1]
    for x_m in STATIONS.values():
        assert deck.WINDOW_M[0] <= x_m <= deck.WINDOW_M[1]


def test_the_core_mesh_is_finer_than_the_far_field():
    text = deck.generate(Design.load(BASELINE))
    mesh_lines = [ln for ln in text.splitlines() if ln.startswith("&MESH")]

    def i_cells(line: str) -> int:
        return int(line.split("IJK=")[1].split(",")[0])

    # the core spans 180 m against the far upstream's 300 m, and still has more
    # cells along x -- that is what "finer" means here
    assert i_cells(mesh_lines[1]) > i_cells(mesh_lines[0])


def test_mesh_spans_are_exact_multiples_of_their_own_dx():
    # misaligned interfaces are the classic multi-mesh FDS bug
    core_span = deck.CORE_M[1] - deck.CORE_M[0]
    up_span = deck.CORE_M[0] - deck.WINDOW_M[0]
    down_span = deck.WINDOW_M[1] - deck.CORE_M[1]
    coarse = deck.FINE_DX_M * deck.COARSE_RATIO
    assert core_span % deck.FINE_DX_M == 0
    assert up_span % coarse == 0
    assert down_span % coarse == 0


def test_the_portals_supply_upstream_and_open_downstream():
    text = deck.generate(Design.load(BASELINE))
    assert "MB='XMIN'" in text and "SURF_ID='SUPPLY'" in text
    assert "MB='XMAX'" in text and "SURF_ID='OPEN'" in text
    # inflow is a NEGATIVE velocity on XMIN
    assert "VEL=-" in text


def test_a_bored_tunnel_is_stair_stepped_and_a_test_rig_is_a_box():
    bored = deck.generate(Design.load(BASELINE))
    boxed = deck.generate(Design.load(TEST_RIG))
    # the circular bore needs many OBST rows to approximate the arc;
    # the rectangular rig needs only its walls
    assert bored.count("&OBST") > boxed.count("&OBST")
