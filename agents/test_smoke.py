"""Smoke test: exercise LLMProxy + JSON extraction + state filter + (optional) game client.

Runs without a game instance — the game connectivity test is skipped
gracefully if the mod HTTP server isn't reachable.

Usage:
    python test_smoke.py
"""
from __future__ import annotations

import json
import traceback

import httpx

from game_client import GameClient
from llm_client import LLMClient, extract_json
from state_filter import for_combat, for_economy, for_strategic


def test_json_extraction():
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json('prefix ```json\n{"b": 2}\n```  suffix') == {"b": 2}
    assert extract_json('noise {"c": {"d": 3}} tail') == {"c": {"d": 3}}
    print("[ok] json extraction")


def test_state_filter():
    sample = {
        "state_type": "monster",
        "run": {"act": 1, "floor": 3},
        "player": {
            "character": "ironclad", "hp": 60, "max_hp": 80, "gold": 120, "energy": 3,
            "hand": [{"name": "Strike"}], "deck": [{}, {}, {}],
            "relics": [{"id": "Burning Blood"}],
            "potions": [{"id": "Energy"}],
        },
        "battle": {"round": 1, "turn": "player", "enemies": [{"entity_id": "JAW_WORM_0", "hp": 40}]},
    }
    c = for_combat(sample)
    assert c["battle"]["enemies"][0]["entity_id"] == "JAW_WORM_0"
    assert c["player"]["energy"] == 3
    s = for_strategic(sample)
    assert s["player"]["deck"] == [{}, {}, {}]
    e = for_economy(sample)
    assert e["player"]["gold"] == 120
    assert "hand" not in e["player"]
    print("[ok] state filter")


def test_llm_roundtrip():
    llm = LLMClient(model="4o-mini")
    out = llm.generate_json(
        system='Return ONLY JSON: {"pong": true}.',
        query="ping",
        session_id="smoke_test",
    )
    assert out.get("pong") is True, f"unexpected: {out}"
    print("[ok] LLM roundtrip:", out)


def test_game_reachable():
    g = GameClient()
    try:
        state = g.get_state("json")
    except httpx.HTTPError as e:
        print(f"[skip] game not running: {e}")
        return
    print("[ok] game state_type =", state.get("state_type") if isinstance(state, dict) else type(state))


if __name__ == "__main__":
    failures = 0
    for t in (test_json_extraction, test_state_filter, test_llm_roundtrip, test_game_reachable):
        try:
            t()
        except Exception as e:
            print(f"[FAIL] {t.__name__}: {e}")
            traceback.print_exc()
            failures += 1
    print("\nAll tests passed." if failures == 0 else f"\n{failures} test(s) failed.")
