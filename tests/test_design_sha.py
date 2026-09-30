"""The design SHA a saved design records is the one its results carry."""
from solit2.engines.reduced import envelope
from solit2.schema.design import Design

EXAMPLE = "examples/designs/road-tunnel-twin-bore.json"


def test_thedesign_sha_is_public_and_is_what_a_result_carries():
    design = Design.load(EXAMPLE)
    assert envelope.run(design).meta["design_sha"] == envelope.design_sha(design)
