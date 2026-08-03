#!/usr/bin/env python3
"""Verify that methodology V2 signals affect gate decisions deterministically."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

import sentry_gate


def save_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def make_session(root: Path) -> Path:
    session_dir = root / "session"
    session_dir.mkdir(parents=True)
    save_json(
        session_dir / "session.json",
        {
            "skill": "methodology-v2-gate-fixture",
            "mode": "smoke",
            "case_warnings": [],
        },
    )

    evals = [
        {
            "id": "route-1",
            "dimension": "route",
            "prompt": "帮我看看这个请求该走哪里",
            "route_expected": "security-review",
            "route_confidence_min": 0.9,
            "route_prediction": {"selected_skill": "security-review", "confidence": 0.6},
        },
        {
            "id": "route-2",
            "dimension": "route",
            "prompt": "帮我看看这个工单该交给谁",
            "route_expected": "finance-review",
            "route_confidence_min": 0.9,
            "route_prediction": {"selected_skill": "finance-review", "confidence": 0.55},
        },
    ]
    save_json(session_dir / "evals.json", evals)

    for case_id in ("route-1", "route-2"):
        save_json(
            session_dir / case_id / "grading.json",
            {
                "eval_id": case_id,
                "summary": {"authoritative_pass_rate": 1.0},
                "assertions": [{"type": "semantic", "passed": True, "evidence": "route selected correctly"}],
            },
        )

    return session_dir


def make_no_route_session(root: Path) -> Path:
    session_dir = root / "no-route-session"
    session_dir.mkdir(parents=True)
    save_json(session_dir / "session.json", {"skill": "methodology-v2-no-route-fixture", "mode": "smoke"})
    save_json(
        session_dir / "evals.json",
        [
            {
                "id": "tool-1",
                "dimension": "tool_call",
                "prompt": "save invoice draft",
                "expected_output": "saveInvoiceDraft(amount=1200000)",
            }
        ],
    )
    save_json(
        session_dir / "tool-1" / "grading.json",
        {
            "eval_id": "tool-1",
            "summary": {"authoritative_pass_rate": 1.0},
            "assertions": [{"type": "semantic", "passed": True, "evidence": "ok"}],
        },
    )
    save_json(session_dir / "gate-policy.json", {"methodology": {"apply_without_route_cases": True}})
    return session_dir


def verify() -> tuple[bool, list[str]]:
    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="skillsentry-methodology-v2-gate-") as tmp:
        session_dir = make_session(Path(tmp))
        result = sentry_gate.build_gate(session_dir)
        methodology = result.get("methodology_v2", {})
        policy = result.get("methodology_policy", {})

        if result.get("verdict") != "CONDITIONAL PASS":
            errors.append(f"gate verdict expected CONDITIONAL PASS, got {result.get('verdict')}")
        if policy.get("status") != "WARN":
            errors.append(f"methodology policy expected WARN, got {policy.get('status')}")
        if policy.get("route_status") != "warn_low_confidence":
            errors.append(f"route status expected warn_low_confidence, got {policy.get('route_status')}")
        if methodology.get("summary", {}).get("overall_recommendation") != "warn":
            errors.append(
                "methodology overall recommendation expected warn, "
                f"got {methodology.get('summary', {}).get('overall_recommendation')}"
            )
        if not any("conditional pass" in str(reason).lower() for reason in result.get("decision_reasons", [])):
            errors.append("decision reasons should mention conditional pass")
        if not result.get("gate_policy", {}).get("source"):
            errors.append("gate result should include gate_policy source")

        save_json(
            session_dir / "gate-policy.json",
            {
                "methodology": {
                    "route": {
                        "block_statuses": ["warn_low_confidence", "block", "block_no_route_precision"],
                        "warn_statuses": ["needs_more_route_metadata", "needs_predictions"],
                    }
                }
            },
        )
        blocked = sentry_gate.build_gate(session_dir)
        blocked_policy = blocked.get("methodology_policy", {})
        if blocked.get("verdict") != "FAIL":
            errors.append(f"custom gate-policy should block release, got {blocked.get('verdict')}")
        if blocked_policy.get("status") != "BLOCK":
            errors.append(f"custom methodology policy expected BLOCK, got {blocked_policy.get('status')}")
        if not str(blocked.get("gate_policy", {}).get("source", "")).endswith("gate-policy.json"):
            errors.append("custom gate-policy.json should be reported as policy source")

        no_route = sentry_gate.build_gate(make_no_route_session(Path(tmp)))
        if no_route.get("methodology_policy", {}).get("status") != "WARN":
            errors.append(
                "apply_without_route_cases=true should enable non-route methodology warnings, "
                f"got {no_route.get('methodology_policy', {}).get('status')}"
            )

    return not errors, errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify gate methodology V2 policy")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ok, errors = verify()
    payload = {"status": "PASS" if ok else "FAIL", "errors": errors}
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"gate methodology v2: {payload['status']}")
        for error in errors:
            print(f"- {error}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
