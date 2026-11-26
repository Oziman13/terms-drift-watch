"""Terms Drift Watch on a local GenLayer network (glsim, 5 validators). A page is watched and read through real consensus
rounds: the leader and four validators each fetch the page and read it with a (mocked) model, and the contract keeps a
snapshot only when they agree. Mocks stay installed for a whole simulator run, so a test that changes the page installs new
mocks between its snapshots. The local simulator ships its own runner hash, so the tests run a copy of the contract with
only that first line swapped.
"""
import json
from pathlib import Path

import pytest

from rpc import RpcError, Sim

ROOT = Path(__file__).resolve().parents[2]
LOCAL_HASH = "5jycge4q8k23462jtb0b9fyey1s9qz928sz2nbrd9mg4sxqg2qng"
TOPICS = ("FEES", "DATA_SHARING", "DISPUTES", "TERMINATION", "LIABILITY", "RENEWAL")
ALICE = "0x3333333333333333333333333333333333333333"
BOB = "0x4444444444444444444444444444444444444444"
T0 = "2026-11-25T12:00:00Z"
T1 = "2026-11-25T13:00:00Z"
T2 = "2026-11-25T14:00:00Z"
URL = "https://terms.example.org/service"
URL_RE = r"https://terms\.example\.org/.*"

Q1 = {
    "FEES": "You pay 10 euros per month for the Plus plan",
    "DATA_SHARING": "We may share your personal data with advertising partners",
    "DISPUTES": "Any dispute is settled by binding arbitration in Dublin under Irish law",
    "TERMINATION": "We may suspend your account at any time with 30 days notice",
    "LIABILITY": "Our total liability is limited to the fees you paid in the last month",
    "RENEWAL": "Your plan renews automatically each month until you cancel in settings",
}
PAGE1 = " ".join("%d. %s." % (i + 1, Q1[t]) for i, t in enumerate(TOPICS))
Q2 = dict(Q1, FEES="You pay 12 euros per month for the Plus plan")
PAGE2 = PAGE1.replace(Q1["FEES"], Q2["FEES"])


def build_local():
    lines = (ROOT / "contracts" / "terms_drift_watch.py").read_text(encoding="utf-8").split("\n")
    lines[0] = '# { "Depends": "py-genlayer:%s" }' % LOCAL_HASH
    out = ROOT / "build" / "terms_drift_watch_local.py"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    return "build/terms_drift_watch_local.py"


CONTRACT = build_local()


def reading(quotes, changes=None, **overrides):
    out = {t: {"state": "PRESENT", "quote": quotes[t], "change": (changes or {}).get(t, "")} for t in TOPICS}
    out.update(overrides)
    return json.dumps(out)


FIRST_PROMPT = r'"previous_quotes": \{\}\}'            # the first snapshot has nothing to compare with
LATER_PROMPT = r'"previous_quotes": \{"[A-Z_]+"'         # a later one is shown the words stored last time


def install(sim, page, first=None, later=None):
    """The web and the model are mocked for the whole run; the model answers the first and the later snapshots differently."""
    llm = {FIRST_PROMPT: first or reading(Q1)}
    if later is not None:
        llm[LATER_PROMPT] = later
    sim.mocks(web={URL_RE: {"method": "GET", "response": {"status": 200, "headers": {}, "body": page}}}, llm=llm)


@pytest.fixture
def sim():
    simulator = Sim()
    try:
        yield simulator
    finally:
        simulator.close()


def start(sim, page=PAGE1, first=None, later=None):
    sim.set_time(T0)
    install(sim, page, first, later)
    contract = sim.deploy(CONTRACT, [], ALICE)
    wid = json.loads(sim.call(contract, "watch", [URL, "Example Service terms"], ALICE))["id"]
    return contract, wid


def test_the_first_snapshot_reads_all_six_topics_after_consensus(sim):
    contract, wid = start(sim)
    out = json.loads(sim.call(contract, "snapshot", [wid], BOB))
    assert out == {"id": wid, "number": 1, "drifted": []}
    watch = sim.read_json(contract, "get_watch_json", [wid])
    topics = watch["snapshots"][0]["topics"]
    assert set(topics) == set(TOPICS) and all(topics[t]["drift"] == "FIRST" and topics[t]["quote"] == Q1[t] for t in TOPICS)
    assert watch["snapshots"][0]["by"] == BOB


def test_a_clause_the_model_calls_changed_is_a_drift_in_the_second_snapshot(sim):
    later = reading(Q1, {t: "SAME" for t in TOPICS} | {"FEES": "CHANGED"})
    contract, wid = start(sim, later=later)
    sim.call(contract, "snapshot", [wid], BOB)
    sim.set_time(T1)
    assert json.loads(sim.call(contract, "snapshot", [wid], BOB)) == {"id": wid, "number": 2, "drifted": ["FEES"]}
    drift = sim.read_json(contract, "get_drift_json", [wid])
    assert drift["topics"]["FEES"]["drifted_in"] == [2] and drift["topics"]["RENEWAL"]["drifted_in"] == []


def test_a_removed_clause_is_found_by_the_second_snapshot(sim):
    later = reading(Q1, {t: "SAME" for t in TOPICS}, DATA_SHARING={"state": "ABSENT", "quote": "", "change": ""})
    contract, wid = start(sim, later=later)
    sim.call(contract, "snapshot", [wid], BOB)
    sim.set_time(T1)
    assert json.loads(sim.call(contract, "snapshot", [wid], BOB))["drifted"] == ["DATA_SHARING"]
    assert sim.read_json(contract, "get_watch_json", [wid])["snapshots"][1]["topics"]["DATA_SHARING"]["drift"] == "REMOVED"


def test_a_quote_that_is_not_on_the_page_is_stored_as_unclear_on_the_network(sim):
    contract, wid = start(sim, first=reading(Q1, FEES={"state": "PRESENT", "quote": "The service is free of charge for everyone", "change": ""}))
    assert json.loads(sim.call(contract, "snapshot", [wid], BOB))["number"] == 1
    topics = sim.read_json(contract, "get_watch_json", [wid])["snapshots"][0]["topics"]
    assert topics["FEES"] == {"state": "UNCLEAR", "quote": "", "drift": "FIRST"} and topics["RENEWAL"]["state"] == "PRESENT"


def test_the_rules_hold_on_the_network(sim):
    contract, wid = start(sim)
    with pytest.raises(RpcError):
        sim.call(contract, "watch", ["http://terms.example.org/x", "A label"], BOB)       # not https
    with pytest.raises(RpcError):
        sim.call(contract, "snapshot", [99], BOB)                                          # unknown watch
    sim.call(contract, "snapshot", [wid], BOB)
    with pytest.raises(RpcError):
        sim.call(contract, "snapshot", [wid], BOB)                                         # a minute has not passed
    assert sim.read(contract, "get_count") == 1
