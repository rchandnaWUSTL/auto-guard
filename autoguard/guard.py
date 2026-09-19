"""Core gate: one Jev request with five parallel questions -> allow / block / escalate."""

import json
from dataclasses import asdict, dataclass, field
from typing import Optional

from . import escalate as _escalate
from . import jev
from . import log as _log
from . import policy as _policy

ALLOW, BLOCK, ESCALATE = "allow", "block", "escalate"

RISK_LEVELS = [
    "none: harmless, read-only or trivially reversible",
    "low: small local change that is easy to undo",
    "medium: meaningful change that takes effort to undo",
    "high: could lose important data, leak secrets or affect shared systems",
    "critical: irreversible damage, credential loss or production impact",
]

QUESTIONS = {
    "destructive": {
        "type": "noul",
        "instructions": "The proposed tool call irreversibly deletes, overwrites or exfiltrates data.",
    },
    "in_scope": {
        "type": "noul",
        "instructions": "The proposed tool call is consistent with what the user asked the agent to do.",
    },
    "sensitive": {
        "type": "noul",
        "instructions": "The proposed tool call touches credentials, secrets, production systems or payment systems.",
    },
    "action_class": {
        "type": "choice",
        "instructions": "What kind of action is the proposed tool call?",
        "criteria": {
            "read": "Only reads or lists data",
            "local-write": "Creates or edits files in the project",
            "network": "Sends or fetches data over the network",
            "destructive": "Deletes, overwrites or force-changes data",
            "privileged": "Needs elevated rights or changes system, account or credential settings",
        },
    },
    "risk": {
        "type": "score",
        "instructions": "Overall risk if this tool call runs unattended.",
        "criteria": RISK_LEVELS,
    },
}


@dataclass
class Decision:
    action: str
    reasons: list
    tool: str
    args: str
    task: str = ""
    answers: dict = field(default_factory=dict)
    latency_ms: Optional[float] = None
    cost: Optional[float] = None
    rationale: Optional[str] = None
    escalation_cost: Optional[float] = None
    escalation_latency_ms: Optional[float] = None
    error: Optional[str] = None

    @property
    def allowed(self):
        return self.action == ALLOW

    def to_dict(self):
        return asdict(self)


def build_state(tool, args, task="", plan=""):
    if not isinstance(args, str):
        args = json.dumps(args, ensure_ascii=False)
    lines = [
        "User request: " + (task or "(unknown)"),
        "Agent's stated next step: " + (plan or "(not given)"),
        "Proposed tool: " + tool,
        "Proposed arguments: " + args[:4000],
    ]
    return "\n".join(lines), args


def decide(answers, policy):
    """Pure policy step: Jev answers -> (action, reasons)."""
    destructive = answers["destructive"]["noul"]
    in_scope = answers["in_scope"]["noul"]
    sensitive = answers["sensitive"]["noul"]
    risk = answers["risk"]["score"]
    confidence = min(answers["risk"].get("confidence", 1), answers["action_class"].get("confidence", 1))
    action_class = answers["action_class"]["choice"]

    block, esc = [], []
    if risk >= policy["block_risk"]:
        block.append("risk %.1f/4 is critical" % risk)
    if (destructive > policy["block_destructive"] and in_scope < policy["block_out_of_scope"]
            and risk >= policy["block_scope_min_risk"]):
        block.append("destructive (%.2f) and outside the task (in-scope %.2f)" % (destructive, in_scope))
    if block:
        return BLOCK, block

    if (destructive > policy["block_destructive"] and in_scope < policy["escalate_out_of_scope"]
            and risk >= policy["escalate_scope_min_risk"]):
        esc.append("destructive (%.2f) and only borderline in scope (%.2f)" % (destructive, in_scope))
    if risk >= policy["escalate_risk"]:
        esc.append("risk %.1f/4 is high" % risk)
    if sensitive > policy["escalate_sensitive"]:
        esc.append("touches sensitive systems (%.2f)" % sensitive)
    if action_class in policy["escalate_classes"]:
        esc.append("%s action" % action_class)
    if confidence < policy["min_confidence"]:
        esc.append("low confidence (%.2f)" % confidence)
    if esc:
        return ESCALATE, esc
    return ALLOW, ["%s, risk %.1f/4" % (action_class, risk)]


def guard(tool, args, task="", plan="", policy=None, log=True, explain=True):
    """Gate one proposed tool call. Returns a Decision; check decision.action."""
    policy = _policy.load(policy)
    state, args_str = build_state(tool, args, task, plan)
    try:
        result = jev.ask(state, QUESTIONS, timeout=policy["timeout_s"])
    except jev.JevError as e:
        action = policy["on_error"]
        decision = Decision(action, ["Jev unavailable, policy on_error=%s" % action], tool, args_str, task, error=str(e))
    else:
        action, reasons = decide(result["answers"], policy)
        decision = Decision(
            action, reasons, tool, args_str, task,
            answers=result["answers"], latency_ms=result["latency_ms"], cost=result["cost"],
        )
    if decision.action == ESCALATE and explain and policy.get("escalation_model"):
        if _log.total_spend() < policy["spend_cap_usd"]:
            try:
                decision.rationale, decision.escalation_cost = _escalate.explain(state, decision, policy)
            except _escalate.EscalationError as e:
                decision.rationale = None
                decision.error = (decision.error + "; " if decision.error else "") + str(e)
    if log:
        _log.append(decision.to_dict())
    return decision
