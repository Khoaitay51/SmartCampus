"""Combine benchmark observations with coverage of the M0–M4 matrix."""
from __future__ import annotations

import argparse
import csv
import os
from collections import defaultdict
from pathlib import Path

PROFILES = ("M0", "M1", "M2", "M3", "M4")
CASE_FIELDS = ("case_id", "scope", "fixture", "implementation", "oracle")
ENTRY_POINTS = {
    "e2e_approval": "notable_fixture", "approval_flow": "fixed_proposal",
    "event_flow": "mqtt_telemetry", "agent_eval": "evaluate_api",
    "local_policy": "offline_probe", "local_contract": "offline_probe",
}
RUN_STATUSES = {"observed", "inconclusive", "setup_error"}
OBSERVATION_FIELDS = (
    "repeat", "run_status", "outcome", "predicted_outcome", "matches_prediction", "policy_agreement",
    "first_block_layer", "rejected_at", "reason_code", "backend_http", "backend_status", "edge_status",
    "edge_frames", "backend_frames", "side_effect_frames", "uncorrelated_frames", "new_edge_commands",
    "room_id", "proposal_id", "edge_command_id", "agent_is_fallback",
    "input_to_valid_proposal_ms", "edge_event_to_valid_proposal_ms",
    "entry_point", "model_source", "evidence",
)
RAW_FIELDS = ("case_id", "profile", "oracle", *OBSERVATION_FIELDS)


def rejected_at(row) -> str:
    layer = row.get("first_block_layer")
    if row["run_status"] == "observed" and layer and layer not in {"none", "unknown"}:
        return layer
    return ""


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))


def read_manifest(path: Path) -> dict:
    cases = {}
    required = {*CASE_FIELDS, "profiles", "expected_observation"}
    for row in read_rows(path):
        if None in row or any(not row.get(field) for field in required):
            raise ValueError(f"Incomplete manifest row for {row.get('case_id')!r}")
        case_id = row["case_id"]
        profile_list = row["profiles"].split("|")
        profiles = set(profile_list)
        if case_id in cases or len(profiles) != len(profile_list) or not profiles <= set(PROFILES):
            raise ValueError(f"Invalid case ID or profile list for {case_id!r}")
        cases[case_id] = row, profiles
    if not cases:
        raise ValueError("The manifest must contain at least one case")
    return cases


def export(manifest: Path, result_paths: list[Path], output: Path) -> None:
    cases = read_manifest(manifest)

    observations = defaultdict(list)
    seen = set()
    for result_path in result_paths:
        for row in read_rows(result_path):
            case_id, profile = row["case_id"], row["profile"]
            case, profiles = cases[case_id]
            repeat = int(row["repeat"])
            run = case_id, profile, repeat
            if (profile not in profiles or row["oracle"] != case["oracle"]
                    or case["implementation"] != "implemented" or run in seen or repeat < 1
                    or row["run_status"] not in RUN_STATUSES
                    or (row["run_status"] == "observed" and not row.get("outcome"))
                    or (row.get("entry_point") and row["entry_point"] != ENTRY_POINTS.get(case["scope"]))):
                raise ValueError(f"Invalid or duplicate result for {run}")
            seen.add(run)
            if row.get("evidence"):
                evidence = (result_path.parent / row["evidence"]).resolve()
                if not evidence.is_file():
                    raise ValueError(f"Evidence file missing for {run}")
                row["evidence"] = Path(os.path.relpath(evidence, output.parent.resolve())).as_posix()
            row["rejected_at"] = rejected_at(row)
            observations[case_id, profile].append(row)

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=(*CASE_FIELDS, "profile", *OBSERVATION_FIELDS))
        writer.writeheader()
        for case_id, (case, applicable) in cases.items():
            for profile in PROFILES:
                base = {key: case[key] for key in CASE_FIELDS} | {"profile": profile}
                runs = observations.get((case_id, profile))
                if runs:
                    for row in sorted(runs, key=lambda row: int(row["repeat"])):
                        writer.writerow(base | {key: row.get(key, "") for key in OBSERVATION_FIELDS})
                else:
                    if profile not in applicable:
                        status = "not_applicable"
                    elif case["implementation"] == "not_e2e":
                        status = "not_e2e"
                    elif case["implementation"] != "implemented":
                        status = "not_implemented"
                    else:
                        status = "not_run"
                    writer.writerow(base | {"run_status": status})


def split_simple_results(combined: Path, directory: Path) -> None:
    rows = read_rows(combined)
    directory.mkdir()
    allow = {"dispatch", "proposal", "policy_allowed", "contract_match", "contract_ok",
             "partial_binding_accepted"}
    pending = {"approval_required": "pending", "needs_verification": "needs_verification",
               "no_proposal": "no_proposal"}
    for profile in PROFILES:
        path = directory / f"results_{profile.lower()}.csv"
        with path.open("x", encoding="utf-8-sig", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(("case_id", "decision", "rejected_at"))
            for row in rows:
                if row["profile"] != profile:
                    continue
                decision, layer = row["run_status"], ""
                if decision == "observed":
                    outcome = row["outcome"]
                    layer = rejected_at(row)
                    if layer:
                        decision = "reject"
                    elif outcome in allow:
                        decision = "allow"
                    else:
                        decision = pending.get(outcome, outcome)
                writer.writerow((row["case_id"], decision, layer))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("results", type=Path, nargs="+")
    args = parser.parse_args()
    try:
        export(args.manifest, args.results, args.output)
    except (KeyError, ValueError, OSError) as exc:
        parser.exit(2, f"Cannot export results: {exc}\n")
    print(args.output)


if __name__ == "__main__":
    main()
