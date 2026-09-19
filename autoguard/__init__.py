"""Auto-Guard: a real-time tool-call firewall on Jev."""

from .guard import ALLOW, BLOCK, ESCALATE, Decision, guard

__all__ = ["guard", "Decision", "ALLOW", "BLOCK", "ESCALATE"]
__version__ = "0.3.0"
