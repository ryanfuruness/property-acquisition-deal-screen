import pytest

from helpers import StubClient
from pipeline.llm import BudgetExceeded, CallRecord, Ledger, ReplayClient, cost_usd, read_api_key


def test_cost_uses_price_table():
    # sonnet assumption: 3 / 15 / 3.75 / 0.30 per million
    assert cost_usd("claude-sonnet-5-5", 1_000_000, 100_000, 200_000, 1_000_000) == pytest.approx(3 + 1.5 + 0.75 + 0.3)
    assert cost_usd("unknown-model", 1_000_000, 0, 0, 0) > 0     # never silently free


def test_ledger_accumulates_and_enforces_budget(tmp_path):
    path = tmp_path / "_ledger.json"
    rec = CallRecord("s", "m", 1, 1, 0, 0, 10.0, 0.1, "tool_use", "t")
    a, b = Ledger(path), Ledger(path)          # two runs sharing one file
    a.add("d1", rec)
    b.add("d2", rec)
    a.add("d1", rec)
    fresh = Ledger(path)
    assert fresh.total_usd == 30.0 and fresh.data["by_deal"] == {"d1": 20.0, "d2": 10.0}
    fresh.check(30.0)
    with pytest.raises(BudgetExceeded):
        fresh.check(25.0)


def test_api_key_from_file_and_never_in_errors(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    key = tmp_path / "k"
    key.write_text("sk-test-123\n")
    monkeypatch.setenv("ANTHROPIC_API_KEY_FILE", str(key))
    assert read_api_key() == "sk-test-123"
    monkeypatch.setenv("ANTHROPIC_API_KEY_FILE", str(tmp_path / "missing"))
    with pytest.raises(RuntimeError) as e:
        read_api_key()
    assert "sk-" not in str(e.value)


def test_replay_reuses_identical_requests(tmp_path):
    inner = StubClient({"s": [{"x": 1}, {"x": 2}]})
    made = []

    def factory(ledger, deal):
        made.append(1)
        return inner
    rc = ReplayClient(factory, None, "d", tmp_path)
    kw = dict(stage="s", model="m", system="sys", content=[{"type": "text", "text": "a"}], tools=[{"name": "t"}])
    first = rc.call_tool(**kw)
    again = rc.call_tool(**kw)
    other = rc.call_tool(**{**kw, "content": [{"type": "text", "text": "b"}]})
    assert first.data == again.data == {"x": 1} and other.data == {"x": 2}
    assert again.call.cost_usd == 0 and again.call.stop_reason == "replayed" and made == [1]
