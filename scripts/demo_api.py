"""
Local API demo: health → plan → replan.

Usage:
  # terminal 1
  .venv/bin/uvicorn src.api.app:app --host 127.0.0.1 --port 8000

  # terminal 2
  .venv/bin/python -m scripts.demo_api

Or run this script alone; it starts an in-process TestClient (no separate server).
Set LIVE_API_BASE=http://127.0.0.1:8000 to hit a running server instead.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta

import httpx


ORIGIN = "Electronic City, Bengaluru"
DESTINATION = "Koramangala, Bengaluru"


def _banner(title: str) -> None:
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def _print_json(label: str, payload: dict) -> None:
    print(f"\n[{label}]")
    print(json.dumps(payload, indent=2, default=str)[:4000])


def run_with_client(client: httpx.Client) -> None:
    _banner("1. GET /health")
    health = client.get("/health")
    print(f"  status={health.status_code} body={health.json()}")

    departure = (datetime.now(timezone.utc) + timedelta(minutes=45)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    plan_body = {
        "origin": ORIGIN,
        "destination": DESTINATION,
        "departure_time": departure,
        "objective": "avoid-traffic",
        "preferences": {
            "time_weight": 8.0,
            "cost_weight": 1.0,
            "congestion_weight": 5.0,
            "avoid_heavy_traffic": True,
            "max_walking_minutes": 12.0,
        },
        "modes": ["DRIVE", "TRANSIT"],
        "invoke_gemini": True,
    }

    _banner("2. POST /plan")
    plan_res = client.post("/plan", json=plan_body)
    plan = plan_res.json()
    print(f"  HTTP {plan_res.status_code}")
    print(f"  ok={plan.get('ok')} error={plan.get('error')}")
    rec = plan.get("recommendation") or {}
    print(f"  recommendation={rec.get('route_id')} time={rec.get('travel_time_minutes')}")
    print(f"  reasons={plan.get('reasons')}")
    print(f"  data_sources={plan.get('data_sources')}")
    print(f"  gemini={plan.get('gemini')}")
    if plan.get("explanation"):
        print(f"  explanation_preview={str(plan['explanation'])[:300]}")

    if not plan.get("ok") or not rec.get("route_id"):
        print("\n  [STOP] /plan did not yield a recommendation; skipping /replan.")
        _print_json("plan_payload", plan)
        return

    replan_body = {
        "request": plan_body,
        "context_change": {
            "traffic_changed": True,
            "context_source": "simulated",
            "target_route_id": rec["route_id"],
            "congestion_delta": 0.55,
            "travel_time_delta_minutes": 22.0,
            "description": f"SIMULATED demo traffic spike on {rec['route_id']}",
        },
        "invoke_gemini": True,
    }

    _banner("3. POST /replan")
    replan_res = client.post("/replan", json=replan_body)
    replan = replan_res.json()
    print(f"  HTTP {replan_res.status_code}")
    print(f"  ok={replan.get('ok')} changed={replan.get('recommendation_changed')}")
    print(f"  previous={replan.get('previous_route_id')} -> new={replan.get('new_route_id')}")
    print(f"  context_source={replan.get('context_change', {}).get('context_source')}")
    print(f"  gemini={replan.get('gemini')}")
    if replan.get("explanation"):
        print(f"  explanation_preview={str(replan['explanation'])[:400]}")

    _banner("4. CURL EXAMPLES")
    print(
        """
  curl -s http://127.0.0.1:8000/health | jq .

  curl -s http://127.0.0.1:8000/plan \\
    -H 'Content-Type: application/json' \\
    -d '{"origin":"Electronic City, Bengaluru","destination":"Koramangala, Bengaluru","invoke_gemini":true}' | jq .

  curl -s http://127.0.0.1:8000/replan \\
    -H 'Content-Type: application/json' \\
    -d @replan_payload.json | jq .
"""
    )


def run_demo() -> None:
    base = os.environ.get("LIVE_API_BASE", "").strip()
    if base:
        _banner(f"LIVE HTTP CLIENT → {base}")
        with httpx.Client(base_url=base, timeout=120.0) as client:
            run_with_client(client)
        return

    _banner("IN-PROCESS TestClient (no separate server)")
    from fastapi.testclient import TestClient
    from src.api.app import create_app

    # Prefer env/.env already configured by the user for live Maps + Gemini.
    try:
        from dotenv import load_dotenv
        load_dotenv(override=False)
    except Exception:
        pass

    with TestClient(create_app()) as client:
        # httpx-compatible wrapper
        class _Wrap:
            def get(self, path):
                return client.get(path)

            def post(self, path, json=None):
                return client.post(path, json=json)

        run_with_client(_Wrap())


if __name__ == "__main__":
    run_demo()
