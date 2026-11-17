"""Run the full SmartCampus benchmark manifest on an isolated Compose stack."""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import os
import subprocess
from collections import Counter
from contextlib import AsyncExitStack
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import aiomqtt
import asyncpg
import httpx

from agent_cases import AGENT_FIXTURES, EVENT_FIXTURES, evaluate_agent, notable_proposal, run_event
from export_results import ENTRY_POINTS, RAW_FIELDS, export, read_manifest, split_simple_results
from guard_probe import FSM_FIXTURES, NOTIFICATION_POLICY_FIXTURES, PAYLOAD_FIXTURES, STATE_FIXTURES
from run_approval import (
    FLAGS, PROFILE_FLAGS, ROOT, SetupError, local_url, parse_approval_cases, run_asyncio, run_case, save_evidence,
    verify_compose,
)

OFFLINE_SERVICES = {
    **dict.fromkeys(FSM_FIXTURES, "api"), **dict.fromkeys(STATE_FIXTURES, "api"),
    **dict.fromkeys(PAYLOAD_FIXTURES, "ai-agent"), "mode_change_waits_for_human": "ai-agent",
    **dict.fromkeys(NOTIFICATION_POLICY_FIXTURES, "ai-agent"),
}
LOCAL_EXPECTED = {
    "allow": "policy_allowed", "deny_policy": "policy_denied", "require_approval": "approval_required",
    "match": "contract_match", "mismatch": "contract_mismatch", "contract_ok": "contract_ok",
    "missing_metadata": "metadata_rejected", "contract_specific": "partial_binding_accepted",
}


def compose(args, *command):
    return ["docker", "compose", "-p", args.project, "-f", str(args.compose_file), *command]


def validate_manifest(manifest, fixtures):
    for row, profiles in manifest.values():
        scope, fixture, oracle = row["scope"], row["fixture"], row["oracle"]
        if scope not in ENTRY_POINTS or row["implementation"] not in {"implemented", "not_e2e", "not_implemented"}:
            raise SetupError(f"{row['case_id']}: unknown scope or implementation status")
        if row["implementation"] != "implemented":
            continue
        supported = (
            (scope in {"approval_flow", "e2e_approval"} and profiles <= {"M3", "M4"})
            or (scope == "agent_eval" and fixture in AGENT_FIXTURES
                and oracle in {
                    "rubric_correct", "verify_evidence",
                    "abstain_noise", "systemic_alert", "resist_ipi", "reject_unsafe_lock",
                })
            or (scope == "event_flow" and fixture in EVENT_FIXTURES and oracle == "allow")
            or (scope in {"local_policy", "local_contract"}
                and fixture in OFFLINE_SERVICES and oracle in LOCAL_EXPECTED)
        )
        if not supported:
            raise SetupError(f"{row['case_id']}: no adapter for {scope}/{fixture}/{oracle}")
    approvals = {}
    rows = [row for row, _ in manifest.values()]
    for profile in PROFILE_FLAGS:
        for scope in ("approval_flow", "e2e_approval"):
            case_ids = [row["case_id"] for row, profiles in manifest.values() if row["scope"] == scope
                        and profile in profiles and row["implementation"] == "implemented"]
            if case_ids:
                approvals.update(((profile, case.case_id), case) for case in parse_approval_cases(
                    rows, fixtures, profile, case_ids, scope=scope,
                ))
    return approvals


async def prepare_profile(args, backend):
    if args.manage_compose:
        env = os.environ | {key: str(value).lower() for key, value in zip(FLAGS, PROFILE_FLAGS[args.profile])}
        await asyncio.to_thread(
            subprocess.run, compose(args, "up", "-d", "api", "ai-agent"),
            cwd=args.compose_file.parent, env=env, check=True, timeout=120,
        )
    await asyncio.to_thread(verify_compose, args)
    hitl = PROFILE_FLAGS[args.profile][2]
    try:
        async with asyncio.timeout(30):
            while True:
                try:
                    response = await backend.get("/api/recommendations/hitl/status", timeout=2)
                    if response.is_success and response.json().get("hitl_enabled") is hitl:
                        break
                except httpx.TransportError:
                    pass
                await asyncio.sleep(0.4)
    except TimeoutError as exc:
        raise SetupError(f"{args.profile}: Backend did not reach the expected HITL state") from exc


def record_model_config(args, output):
    keys = ["LLM_PROVIDER", "AGENT", "OLLAMA_MODEL"]
    script = "import json, os, sys; print(json.dumps({key: os.getenv(key) for key in sys.argv[1:]}))"
    result = subprocess.run(compose(args, "exec", "-T", "ai-agent", "python", "-c", script, *keys),
                            cwd=args.compose_file.parent, capture_output=True, text=True, timeout=20)
    if result.returncode:
        raise SetupError(f"{args.profile}: cannot read configured model identifiers")
    (output / "model_config.json").write_text(result.stdout, encoding="utf-8")


async def evaluate_local(args, case, evidence):
    fixture = case["fixture"]
    service = OFFLINE_SERVICES[fixture]
    result = await asyncio.to_thread(
        subprocess.run, compose(args, "exec", "-T", service, "python", "-", fixture),
        cwd=args.compose_file.parent, input=Path(__file__).with_name("guard_probe.py").read_text(encoding="utf-8"),
        capture_output=True, text=True, encoding="utf-8", timeout=20,
    )
    evidence["probe_service"] = service
    evidence["probe_returncode"] = result.returncode
    if result.returncode:
        evidence["probe_stderr"] = result.stderr
        raise SetupError(f"Offline probe failed in {service}")
    probe = json.loads(result.stdout)
    evidence["probe_result"] = probe
    expected = LOCAL_EXPECTED[case["oracle"]]
    predicted = "policy_allowed" if fixture in NOTIFICATION_POLICY_FIXTURES and args.profile == "M0" else expected
    return {
        **{key: probe[key] for key in ("outcome", "first_block_layer", "reason_code") if key in probe},
        "predicted_outcome": predicted, "matches_prediction": probe["outcome"] == predicted,
        "policy_agreement": probe["outcome"] == expected,
    }


async def run_other_case(args, services, case, repeat):
    scope = case["scope"]
    row = {"case_id": case["case_id"], "profile": args.profile,
           "repeat": repeat, "oracle": case["oracle"], "run_status": "observed",
           "entry_point": ENTRY_POINTS[scope],
           "model_source": args.model_source if scope in {"agent_eval", "event_flow"} else "not_used"}
    evidence = {"fixture": case["fixture"], "scope": scope, "started_at": datetime.now(timezone.utc)}
    try:
        if scope == "agent_eval":
            result = await evaluate_agent(args, services, case, evidence)
        elif scope == "event_flow":
            result = await run_event(args, services, case, evidence)
        else:
            result = await evaluate_local(args, case, evidence)
        row.update(result)
        if row["run_status"] == "observed" and not row.get("outcome"):
            raise SetupError("Adapter returned no observed outcome")
    except (SetupError, TimeoutError, httpx.HTTPError, aiomqtt.MqttError, asyncpg.PostgresError,
            subprocess.TimeoutExpired, ValueError, KeyError, OSError) as error:
        row["run_status"] = "setup_error" if isinstance(error, SetupError) else "inconclusive"
        row["reason_code"] = type(error).__name__
        if "backend_http" in evidence:
            row["backend_http"] = evidence["backend_http"]
        evidence["error_type"] = type(error).__name__
    return save_evidence(args.output, row, evidence)


async def run_profile(args, manifest, approvals, output, backend, edge, edge_dsn, backend_dsn):
    selected = [row for row, profiles in manifest.values()
                if args.profile in profiles and row["implementation"] == "implemented"]
    args.output = output
    output.mkdir()
    result_file = output / "results.csv"
    counts = Counter()
    with result_file.open("x", encoding="utf-8", newline="") as file:
        csv.DictWriter(file, fieldnames=RAW_FIELDS).writeheader()
    if not selected:
        return result_file, counts
    await prepare_profile(args, backend)
    if any(row["scope"] in {"agent_eval", "event_flow", "e2e_approval"} for row in selected):
        await asyncio.to_thread(record_model_config, args, output)
    async with AsyncExitStack() as stack:
        edge_db = await asyncpg.connect(edge_dsn, timeout=5, command_timeout=10)
        stack.push_async_callback(edge_db.close)
        backend_db = await asyncpg.connect(backend_dsn, timeout=5, command_timeout=10)
        stack.push_async_callback(backend_db.close)
        services = edge_db, backend_db, edge, backend
        with result_file.open("a", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=RAW_FIELDS)
            for repeat in range(1, args.repeat + 1):
                for case in selected:
                    case_id = case["case_id"]
                    approval = approvals.get((args.profile, case_id))
                    if approval:
                        source = notable_proposal if case["scope"] == "e2e_approval" else None
                        row = await run_case(args, services, approval, repeat, proposal_source=source)
                    else:
                        row = await run_other_case(args, services, case, repeat)
                    writer.writerow(row)
                    file.flush()
                    print(args.profile, case_id, row["run_status"], row.get("outcome", row.get("reason_code", "")),
                          flush=True)
                    counts[row["run_status"]] += 1
                    if row["run_status"] == "observed":
                        if row.get("policy_agreement") is False:
                            counts["policy_disagreements"] += 1
                        if row.get("matches_prediction", row.get("policy_agreement")) is False:
                            counts["unexpected_results"] += 1
    return result_file, counts


async def run(args):
    profiles = args.profiles or list(PROFILE_FLAGS)
    base_output = args.output.resolve()
    manifest_bytes = args.manifest.read_bytes()
    fixture_bytes = args.fixtures.read_bytes()
    compose_hash = sha256(args.compose_file.read_bytes()).hexdigest()
    base_output.mkdir(parents=True, exist_ok=False)
    manifest_path = base_output / "manifest.csv"
    manifest_path.write_bytes(manifest_bytes)
    (base_output / "approval_fixtures.json").write_bytes(fixture_bytes)
    manifest = read_manifest(manifest_path)
    approvals = validate_manifest(manifest, json.loads(fixture_bytes))
    (base_output / "run_metadata.json").write_text(json.dumps({
        "schema_version": 2, "started_at": datetime.now(timezone.utc).isoformat(),
        "model_source": args.model_source, "profiles": profiles, "repeat": args.repeat,
        "profile_flags": {profile: dict(zip(FLAGS, PROFILE_FLAGS[profile])) for profile in profiles},
        "manifest": str(args.manifest), "manifest_sha256": sha256(manifest_bytes).hexdigest(),
        "fixtures": str(args.fixtures), "fixtures_sha256": sha256(fixture_bytes).hexdigest(),
        "project": args.project, "compose_file": str(args.compose_file), "compose_sha256": compose_hash,
        "agent_timeout": args.agent_timeout, "snapshot_timeout": args.snapshot_timeout,
        "mqtt_window": args.mqtt_window,
    }, indent=2) + "\n", encoding="utf-8")
    edge_dsn = local_url(os.environ["BENCH_EDGE_DSN"], {"postgresql", "postgres"})
    backend_dsn = local_url(os.environ["BENCH_BACKEND_DSN"], {"postgresql", "postgres"})
    if edge_dsn == backend_dsn:
        raise SetupError("Use distinct test databases")
    token = os.environ["BENCH_APPROVAL_TOKEN"]
    edge_url = local_url(args.edge_url, {"http", "https"})
    backend_url = local_url(args.backend_url, {"http", "https"})
    files = []
    summary = {}
    failed = False
    for profile in profiles:
        args.profile = profile
        # Use fresh HTTP connections for each configuration after a Compose restart.
        async with (
            httpx.AsyncClient(base_url=edge_url, trust_env=False, timeout=15) as edge,
            httpx.AsyncClient(base_url=backend_url, trust_env=False, timeout=15,
                              headers={"Authorization": f"Bearer {token}"}) as backend,
        ):
            result, counts = await run_profile(
                args, manifest, approvals, base_output / profile, backend, edge, edge_dsn, backend_dsn,
            )
        files.append(result)
        summary[profile] = {key: counts[key] for key in (
            "observed", "inconclusive", "setup_error", "unexpected_results", "policy_disagreements",
        )}
        failed |= bool(counts["inconclusive"] or counts["setup_error"] or counts["unexpected_results"])
    combined = base_output / "results_m0_m4.csv"
    export(manifest_path, files, combined)
    split_simple_results(combined, base_output / "by_profile")
    (base_output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(combined)
    return int(failed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "experiment/e2e_cases.csv")
    parser.add_argument("--fixtures", type=Path, default=ROOT / "experiment/approval_fixtures.json")
    parser.add_argument("--profile", action="append", dest="profiles", choices=list(PROFILE_FLAGS))
    parser.add_argument("--project", required=True)
    parser.add_argument("--compose-file", type=Path, required=True)
    parser.add_argument("--manage-compose", action="store_true", help="Apply test profile flags and start test services")
    parser.add_argument("--isolated-test-stack", action="store_true", help="Confirm the project and broker are isolated")
    parser.add_argument("--backend-url", default="http://127.0.0.1:8001")
    parser.add_argument("--edge-url", default="http://127.0.0.1:8000")
    parser.add_argument("--mqtt-host", choices=("localhost", "127.0.0.1", "::1"), default="127.0.0.1")
    parser.add_argument("--mqtt-port", type=int, default=1883)
    parser.add_argument("--model-source", choices=("live", "fixture"), default="live", help="Label the configured model source in the run metadata")
    parser.add_argument("--agent-timeout", type=float, default=90)
    parser.add_argument("--snapshot-timeout", type=float, default=5)
    parser.add_argument("--mqtt-window", type=float, default=2)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.isolated_test_stack:
        parser.error("--isolated-test-stack is required")
    if not args.manage_compose and (not args.profiles or len(args.profiles) != 1):
        parser.error("Select one preconfigured --profile or use --manage-compose")
    if args.profiles and len(set(args.profiles)) != len(args.profiles):
        parser.error("Each profile can be selected once")
    if (args.repeat < 1 or not 1 <= args.mqtt_port <= 65535
            or any(not math.isfinite(n) or n <= 0 for n in (args.agent_timeout, args.snapshot_timeout, args.mqtt_window))):
        parser.error("Repeat, port and timeouts must be valid positive values")
    args.compose_file = args.compose_file.resolve()
    if args.output is None:
        args.output = ROOT / "benchmark_local/runs" / f"full-{uuid4().hex}"
    try:
        return run_asyncio(run(args))
    except (SetupError, KeyError, ValueError, OSError, subprocess.SubprocessError,
            httpx.HTTPError, asyncpg.PostgresError) as error:
        parser.exit(2, f"Benchmark preflight/export failed: {type(error).__name__}: {error if isinstance(error, SetupError) else ''}\n")


if __name__ == "__main__":
    raise SystemExit(main())
