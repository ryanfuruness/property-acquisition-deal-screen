"""The only place the pipeline talks to a model.

Stages call :meth:`ModelClient.call_tool` with content blocks and one or more tool schemas and
get back the tool input the model produced plus a :class:`CallRecord` (tokens, cost, time).
Tests replace the client with a stub (see ``tests/pipeline/stubs.py``), so no test calls the API.

Prompt caching: the OM is sent once as a native PDF document block marked ``cache_control``
and is reused by the extraction and the review pass. The cached prefix is tools -> system ->
messages, so both OM calls send the same tools and the same system prompt; the stage
instruction comes after the document and names the tool to call.

The API key is read from ``ANTHROPIC_API_KEY`` or from the file named in
``ANTHROPIC_API_KEY_FILE``. It is never printed, logged or written anywhere.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from string import Template
from typing import Any, Protocol

from . import config


class ModelError(RuntimeError):
    """The model did not return a usable tool call."""


class BudgetExceeded(RuntimeError):
    """The spend ledger is above the configured budget."""


@dataclass
class CallRecord:
    stage: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int
    cost_usd: float
    duration_s: float
    stop_reason: str | None
    tool: str | None

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class ToolResult:
    tool: str
    data: dict
    call: CallRecord


def load_prompt(name: str, **subs: str) -> str:
    """Read ``pipeline/prompts/<name>.md`` and substitute ``$placeholders``."""
    text = (config.PROMPTS_DIR / f"{name}.md").read_text()
    return Template(text).substitute(**subs) if subs else text


def cost_usd(model: str, input_tokens: int, output_tokens: int, cache_write: int, cache_read: int) -> float:
    """Price a call with :data:`config.PRICES_USD_PER_MTOK` (assumed list prices)."""
    p = config.PRICES_USD_PER_MTOK.get(model, config.FALLBACK_PRICE)
    return round((input_tokens * p["input"] + output_tokens * p["output"]
                  + cache_write * p["cache_write"] + cache_read * p["cache_read"]) / 1e6, 6)


class ModelClient(Protocol):
    """Interface the stages depend on."""

    def call_tool(self, *, stage: str, model: str, system: str, content: list[dict],
                  tools: list[dict], tool_name: str | None = None,
                  max_tokens: int = config.MAX_OUTPUT_TOKENS) -> ToolResult:
        """Send one user turn; return the input of the tool the model called.

        ``tool_name`` is the tool the stage expects. When it is ``None`` any of ``tools`` is
        acceptable; OM calls send the same tool list each time so the cache prefix matches.
        """
        ...


def read_api_key() -> str:
    """API key from the environment or a key file. Raises if neither is set; never echoes the key."""
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        path = os.environ.get("ANTHROPIC_API_KEY_FILE", "").strip()
        if path:
            try:
                key = Path(path).expanduser().read_text().strip()
            except OSError as exc:
                raise RuntimeError(f"cannot read ANTHROPIC_API_KEY_FILE ({exc.__class__.__name__})") from None
    if not key:
        raise RuntimeError("set ANTHROPIC_API_KEY or ANTHROPIC_API_KEY_FILE")
    return key


class AnthropicClient:
    """:class:`ModelClient` backed by the Anthropic Messages API, with a spend ledger."""

    def __init__(self, ledger: "Ledger", deal_id: str):
        import anthropic

        self._client = anthropic.Anthropic(api_key=read_api_key(), max_retries=config.MAX_RETRIES,
                                           timeout=config.REQUEST_TIMEOUT_S)
        self.ledger = ledger
        self.deal_id = deal_id

    def call_tool(self, *, stage: str, model: str, system: str, content: list[dict],
                  tools: list[dict], tool_name: str | None = None,
                  max_tokens: int = config.MAX_OUTPUT_TOKENS) -> ToolResult:
        # Current models reject forced tool_choice, so the choice is "auto" and the instruction names
        # the tool; a reply without a tool call gets one reminder turn.
        expected = tool_name or ", ".join(t["name"] for t in tools)
        messages = [{"role": "user", "content": content}]
        record = None
        for attempt in (1, 2):
            resp, record = self._send(stage, model, system, tools, messages, max_tokens, record)
            tool_block = next((b for b in resp.content if b.type == "tool_use"), None)
            if tool_block is not None:
                break
            messages += [{"role": "assistant", "content": [b.model_dump(exclude_none=True) for b in resp.content
                                                           if b.type == "text"] or [{"type": "text", "text": "..."}]},
                         {"role": "user", "content": f"Call the tool `{expected}` now with your answer."}]
        if tool_block is None:
            raise ModelError(f"{stage}: model returned no tool call (stop_reason={resp.stop_reason})")
        if resp.stop_reason == "max_tokens":
            raise ModelError(f"{stage}: output hit max_tokens ({max_tokens}); tool input is truncated")
        if tool_name and tool_block.name != tool_name:
            raise ModelError(f"{stage}: model called {tool_block.name!r}, expected {tool_name!r}")
        record.tool = tool_block.name
        return ToolResult(tool=tool_block.name, data=dict(tool_block.input), call=record)

    def _send(self, stage: str, model: str, system: str, tools: list[dict], messages: list[dict],
              max_tokens: int, previous: CallRecord | None) -> tuple[Any, CallRecord]:
        """One API request; usage is added to ``previous`` (a retry is part of the same call record)."""
        started = time.monotonic()
        with self._client.messages.stream(model=model, max_tokens=max_tokens, system=system, tools=tools,
                                          tool_choice={"type": "auto"}, messages=messages) as stream:
            resp = stream.get_final_message()
        u = resp.usage
        cw = getattr(u, "cache_creation_input_tokens", 0) or 0
        cr = getattr(u, "cache_read_input_tokens", 0) or 0
        rec = CallRecord(stage=stage, model=model, input_tokens=u.input_tokens, output_tokens=u.output_tokens,
                         cache_creation_input_tokens=cw, cache_read_input_tokens=cr,
                         cost_usd=cost_usd(model, u.input_tokens, u.output_tokens, cw, cr),
                         duration_s=round(time.monotonic() - started, 2), stop_reason=resp.stop_reason, tool=None)
        self.ledger.add(self.deal_id, rec)
        if previous is not None:
            for k in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens",
                      "cost_usd", "duration_s"):
                setattr(rec, k, round(getattr(rec, k) + getattr(previous, k), 6))
        return resp, rec


class ReplayClient:
    """Wraps a client and reuses the stored response when an identical request was made before.

    For development: re-running the code-side stages of a deal costs nothing as long as the
    model requests are byte-identical. Responses live in ``runs/<deal_id>/.model_cache/``.
    A replayed call is recorded with zero cost and ``stop_reason: "replayed"``.
    """

    def __init__(self, inner_factory, ledger: "Ledger", deal_id: str, cache_dir: Path):
        self._inner_factory, self._inner = inner_factory, None
        self.ledger, self.deal_id, self.cache_dir = ledger, deal_id, cache_dir

    def call_tool(self, *, stage: str, model: str, system: str, content: list[dict], tools: list[dict],
                  tool_name: str | None = None, max_tokens: int = config.MAX_OUTPUT_TOKENS) -> ToolResult:
        import hashlib

        key = hashlib.sha256(json.dumps([stage, model, system, content, tools, tool_name, max_tokens],
                                        sort_keys=True).encode()).hexdigest()[:32]
        path = self.cache_dir / f"{stage}-{key}.json"
        if path.exists():
            data = json.loads(path.read_text())
            rec = CallRecord(stage=stage, model=model, input_tokens=0, output_tokens=0,
                             cache_creation_input_tokens=0, cache_read_input_tokens=0, cost_usd=0.0,
                             duration_s=0.0, stop_reason="replayed", tool=data["tool"])
            return ToolResult(tool=data["tool"], data=data["data"], call=rec)
        if self._inner is None:
            self._inner = self._inner_factory(self.ledger, self.deal_id)
        res = self._inner.call_tool(stage=stage, model=model, system=system, content=content, tools=tools,
                                    tool_name=tool_name, max_tokens=max_tokens)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"tool": res.tool, "data": res.data, "original_call": res.call.as_dict()}))
        return res


class Ledger:
    """Cumulative spend across runs, persisted in ``runs/_ledger.json``."""

    def __init__(self, path: Path = config.LEDGER_PATH):
        self.path = path
        self.data = {"total_usd": 0.0, "calls": 0, "by_deal": {}, "entries": []}
        if path.exists():
            self.data = json.loads(path.read_text())

    @property
    def total_usd(self) -> float:
        return float(self.data.get("total_usd", 0.0))

    def check(self, budget_usd: float) -> None:
        if self.total_usd > budget_usd:
            raise BudgetExceeded(f"ledger total USD {self.total_usd:.2f} exceeds the budget of USD "
                                 f"{budget_usd:.2f}; raise DEAL_SCREEN_BUDGET_USD or --budget to continue")

    def add(self, deal_id: str, record: CallRecord) -> None:
        """Add a call's cost. Re-reads the file under a lock, so concurrent runs do not lose updates."""
        import fcntl

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path.with_suffix(".lock"), "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if self.path.exists():
                self.data = json.loads(self.path.read_text())
            self.data["total_usd"] = round(self.total_usd + record.cost_usd, 6)
            self.data["calls"] = int(self.data.get("calls", 0)) + 1
            by = self.data.setdefault("by_deal", {})
            by[deal_id] = round(by.get(deal_id, 0.0) + record.cost_usd, 6)
            self.data.setdefault("entries", []).append({
                "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "deal_id": deal_id, "stage": record.stage,
                "model": record.model, "cost_usd": record.cost_usd,
                "tokens": {"input": record.input_tokens, "output": record.output_tokens,
                           "cache_write": record.cache_creation_input_tokens,
                           "cache_read": record.cache_read_input_tokens},
            })
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=1))
            tmp.replace(self.path)
