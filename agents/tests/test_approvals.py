import pytest

from mc_agents.approvals import MemoryStore, NotAuthorized, decide, request

ACTS = [{"type": "discount", "discount_bps": 1200}]


def test_flow_and_higher_role_may_approve():
    st = MemoryStore()
    assert request(st, "a1", "q", ACTS, "revops_lead").status == "pending"
    done = decide(st, "a1", "head_of_revenue", True)
    assert done.status == "approved" and done.decided_by == "head_of_revenue"


def test_lower_or_unknown_role_rejected():
    st = MemoryStore()
    request(st, "a1", "q", ACTS, "revops_lead")
    for role in ("account_manager", "visitor"):
        with pytest.raises(NotAuthorized):
            decide(st, "a1", role, True)
    assert st.get("a1")["status"] == "pending"


def test_double_decision_and_bad_requests():
    st = MemoryStore()
    request(st, "a1", "q", ACTS, "revops_lead")
    assert decide(st, "a1", "revops_lead", False).status == "rejected"
    with pytest.raises(ValueError):
        decide(st, "a1", "revops_lead", True)
    with pytest.raises(ValueError):
        request(st, "a1", "q", ACTS, "revops_lead")
    with pytest.raises(ValueError):
        request(st, "a2", "q", [], "revops_lead")
    with pytest.raises(ValueError):
        request(st, "a2", "q", ACTS, "ceo")
    with pytest.raises(KeyError):
        decide(st, "zz", "revops_lead", True)
