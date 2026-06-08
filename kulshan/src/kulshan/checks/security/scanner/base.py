"""Base scanner class and finding model."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum


class Severity(Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


@dataclass
class Finding:
    check_id: str
    title: str
    severity: Severity
    category: str
    resource_type: str
    resource_id: str
    resource_arn: str = ""
    region: str = "global"
    description: str = ""
    remediation: str = ""
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ScanResult:
    findings: List[Finding] = field(default_factory=list)
    resources: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseScanner:
    """Base class for all security scanners."""

    category: str = "unknown"
    
    def __init__(self, session, regions, progress=None, task_id=None):
        self.session = session
        self.regions = regions
        self.progress = progress
        self.task_id = task_id
        self.findings: List[Finding] = []
        self.resources: Dict[str, Any] = {}
        self.errors: List[str] = []

    def scan(self) -> ScanResult:
        """Override in subclass. Collect data and run checks."""
        raise NotImplementedError

    def add_finding(self, **kwargs):
        kwargs.setdefault("category", self.category)
        self.findings.append(Finding(**kwargs))

    def advance(self):
        if self.progress and self.task_id:
            self.progress.advance(self.task_id)
