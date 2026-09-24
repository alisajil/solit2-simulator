"""Every SOLIT2 rule the checker runs, in report order."""
from solit2.compliance.rules.lab_rules import RULES as _LAB
from solit2.compliance.rules.test_rules import RULES as _TEST
from solit2.compliance.rules.transfer_rules import RULES as _TRANSFER

REGISTRY = _TEST + _LAB + _TRANSFER
