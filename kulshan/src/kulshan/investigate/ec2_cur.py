"""Compatibility imports for the first EC2 CUR investigation proof."""

from kulshan.investigate.ec2 import investigate_ec2_cur
from kulshan.investigate.errors import CurInvestigationError
from kulshan.investigate.models import DeltaRow, Ec2InvestigationBrief, EvidenceItem

__all__ = [
    "CurInvestigationError",
    "DeltaRow",
    "Ec2InvestigationBrief",
    "EvidenceItem",
    "investigate_ec2_cur",
]
