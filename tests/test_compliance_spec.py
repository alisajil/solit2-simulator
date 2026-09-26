import json

import pytest
from pydantic import ValidationError

from solit2.compliance.spec import ComplianceSpec, load_spec

FIXTURE = "tests/fixtures/compliance/minimal.spec.json"


def test_the_spec_loads_its_designs_relative_to_itself():
    loaded = load_spec(FIXTURE)
    assert set(loaded.tests) == {"A"}
    assert loaded.tests["A"].fire.fire_class == "A"
    assert loaded.installation.tunnel.section == "bored"
    assert loaded.spec.facts.pallet_moisture_pct.value == 14.0
    assert loaded.spec.facts.pallet_moisture_pct.evidence.cite() == "fixture certificate, p. 1"
    assert loaded.project_rules_path is None


def _raw() -> dict:
    return json.loads(open(FIXTURE).read())


def test_a_misspelt_fact_is_refused_not_ignored():
    raw = _raw()
    raw["facts"]["pallet_moisture"] = raw["facts"].pop("pallet_moisture_pct")
    with pytest.raises(ValidationError, match="pallet_moisture"):
        ComplianceSpec.model_validate(raw)


def test_a_fact_without_evidence_is_refused():
    raw = _raw()
    raw["facts"]["pallet_moisture_pct"] = {"value": 14.0}
    with pytest.raises(ValidationError, match="evidence"):
        ComplianceSpec.model_validate(raw)


def test_a_class_a_test_design_is_required():
    raw = _raw()
    raw["test_designs"] = {"B": raw["test_designs"]["A"]}
    with pytest.raises(ValidationError, match="Class A"):
        ComplianceSpec.model_validate(raw)


def test_a_missing_design_file_names_the_field(tmp_path):
    raw = _raw()
    raw["installation_design"] = "nowhere.json"
    path = tmp_path / "s.spec.json"
    path.write_text(json.dumps(raw))
    with pytest.raises(FileNotFoundError, match="installation_design"):
        load_spec(path)
