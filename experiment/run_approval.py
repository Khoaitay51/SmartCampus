"""Run data-driven approval scenarios against an isolated SmartCampus stack."""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import os
import subprocess
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import aiomqtt
import asyncpg
import httpx

if __package__:
    from .export_results import ENTRY_POINTS, RAW_FIELDS, read_rows, rejected_at
else:
    from export_results import ENTRY_POINTS, RAW_FIELDS, read_rows, rejected_at

ROOT = Path(__file__).resolve().parents[1]
FLAGS = ("SAFETY_PROMPT_GUARD_ENABLED", "SAFETY_FSM_ENABLED",
         "SAFETY_HITL_ENABLED", "SAFETY_TOCTOU_BINDING_ENABLED")


PROFILE_FLAGS = {
    "M0": (False, False, False, False),
    "M1": (True, False, False, False),
    "M2": (True, True, False, False),
    "M3": (True, True, True, False),
    "M4": (True, True, True, True),
}

STATE_VALUES = {
    "room_mode": {"SAVING", "SELF_STUDY", "LECTURE", "EXAM", "LOCK", "SUSPECTED", "EMERGENCY"},
    "door_state": {"LOCKED", "UNLOCKED"},
    "smoke_state": {"NORMAL", "SUSPECTED", "EMERGENCY"},
}
TIMESTAMP_COLUMNS = {
    "room_mode": "room_state_timestamp",
    "door_state": "room_door_state_timestamp",
    "smoke_state": "room_smoke_state_timestamp",
}
COMMANDS = {
    "fan": ("set_fan", {"state": "on"}, "fan", "on"),
    "buzzer": ("trigger_buzzer", {"pattern": "on"}, "buzzer", "on"),
    "light": ("set_led", {"state": "on"}, "light", "on"),
    "mode_saving": ("set_mode", {"mode": "saving"}, "mode", "saving"),
}


@dataclass(frozen=True)
class Scenario:
    case_id: str
    oracle: str
    initial: dict[str, str]
    command: str
    before_proposal: tuple[tuple[str, str], ...]
    before_approval: tuple[tuple[str, str], ...]
    reason: str
    predicted_outcome: str
    approve_first: str | None
    fixture_name: str = ""


class SetupError(RuntimeError):
    """The run did not reach a verified starting condition."""


class AgentStageError(RuntimeError):
    """The Agent did not produce a proposal eligible for the test."""


def fixture_steps(steps: list[dict], fixture: str) -> tuple[tuple[str, str], ...]:
    if not isinstance(steps, list):
        raise SetupError(f"{fixture}: state changes must be a list")
    for step in steps:
        if not isinstance(step, dict) or len(step) != 1:
            raise SetupError(f"{fixture}: each step must change one known state field")
        field, value = next(iter(step.items()))
        if not isinstance(value, str) or value not in STATE_VALUES.get(field, set()):
            raise SetupError(f"{fixture}: invalid state change for {field}")
    return tuple(next(iter(step.items())) for step in steps)


def read_cases(path: Path, fixtures_path: Path, profile: str,
               selected: list[str] | None, *, scope: str = "approval_flow") -> list[Scenario]:
    fixtures = json.loads(fixtures_path.read_text(encoding="utf-8"))
    return parse_approval_cases(read_rows(path), fixtures, profile, selected, scope=scope)


def parse_approval_cases(rows, fixtures, profile, selected, *, scope):
    if not isinstance(fixtures, dict):
        raise SetupError("Fixture file must be an object keyed by fixture name")
    if selected is None:
        selected = [
            row["case_id"] for row in rows if row.get("scope") == scope
            and row.get("fixture") in fixtures and profile in row.get("profiles", "").split("|")
        ]
    selected_ids = set(selected)
    selected_rows = [row for row in rows if row.get("case_id") in selected_ids]
    if not selected_rows or len(selected_rows) != len(selected_ids):
        raise SetupError("Select cases with exactly one row each in the manifest")

    scenarios = []
    for row in selected_rows:
        case_id, name = row["case_id"], row.get("fixture")
        fixture = fixtures.get(name)
        oracle = row.get("oracle")
        if (row.get("scope") != scope or profile not in row.get("profiles", "").split("|")
                or oracle not in {"allow", "reject_stale", "no_extra_dispatch"} or not isinstance(fixture, dict)):
            raise SetupError(f"{case_id}: unsupported scope, profile, oracle or fixture")
        initial = fixture.get("initial")
        if (not isinstance(initial, dict) or set(initial) != set(STATE_VALUES)
                or any(not isinstance(value, str) or value not in STATE_VALUES[field]
                       for field, value in initial.items())):
            raise SetupError(f"{case_id}: invalid initial state")
        command = fixture.get("command")
        reason = fixture.get("reason")
        if not isinstance(command, str) or command not in COMMANDS or not isinstance(reason, str) or not reason.strip():
            raise SetupError(f"{case_id}: use a known test command and describe its policy rationale")
        predictions = fixture.get("predicted")
        expected = predictions.get(profile) if isinstance(predictions, dict) else None
        approve_first = fixture.get("approve_first")
        if approve_first is not None and (
            not isinstance(approve_first, str)
            or approve_first not in (*COMMANDS, "same_proposal")
        ):
            raise SetupError(f"{case_id}: approve_first must name a test command or same_proposal")
        if (oracle == "no_extra_dispatch") != (approve_first == "same_proposal"):
            raise SetupError(f"{case_id}: duplicate approval needs a matching oracle")
        if expected not in ("dispatch", "stale", "blocked", "duplicate_blocked"):
            raise SetupError(f"{case_id}: specify the predicted outcome for {profile}")
        scenarios.append(Scenario(
            case_id, oracle, initial, command,
            fixture_steps(fixture.get("before_proposal", []), name),
            fixture_steps(fixture.get("before_approval", []), name),
            reason, expected, approve_first, fixture_name=name,
        ))
    return scenarios


def verify_compose(args: argparse.Namespace) -> None:
    expected = tuple(str(value).lower() for value in PROFILE_FLAGS[args.profile])
    for service, flags, values in (
        ("ai-agent", FLAGS, expected),
        ("api", (FLAGS[1], FLAGS[3]), (expected[1], expected[3])),
    ):
        command = ["docker", "compose", "-p", args.project, "-f", str(args.compose_file),
                   "exec", "-T", service, "printenv", *flags]
        result = subprocess.run(command, cwd=args.compose_file.parent, capture_output=True,
                                text=True, timeout=20)
        actual = tuple(line.strip().lower() for line in result.stdout.splitlines())
        if result.returncode or actual != values:
            raise SetupError(f"{service}: cannot verify {args.profile} flags in project {args.project}")


async def seed_room(edge_db, backend_db, room_id: UUID, initial: dict[str, str]) -> None:
    name = f"Benchmark {room_id}"
    async with edge_db.transaction():
        await edge_db.execute(
            "INSERT INTO room (room_id, room_name, room_type) VALUES ($1, $2, 'CLASSROOM')",
            room_id, name,
        )
        await edge_db.execute(
            "INSERT INTO room_state (room_id, room_mode, room_status) VALUES ($1, $2, 'online')",
            room_id, initial["room_mode"],
        )
        await edge_db.execute(
            "INSERT INTO room_door_state (room_id, door_state) VALUES ($1, $2)", room_id, initial["door_state"]
        )
        await edge_db.execute(
            "INSERT INTO room_smoke_state (room_id, smoke_state) VALUES ($1, $2)", room_id, initial["smoke_state"]
        )
    await backend_db.execute(
        """INSERT INTO campus.rooms (id, name, mode, occupancy, door_locked, fan_on)
           VALUES ($1, $2, $3, 0, $4, false)""",
        room_id, name, initial["room_mode"], initial["door_state"] == "LOCKED",
    )


async def read_state(db, room_id: UUID) -> dict:
    record = await db.fetchrow(
        """SELECT room_mode, room_state_timestamp, door_state, room_door_state_timestamp,
                  smoke_state, room_smoke_state_timestamp
           FROM LATERAL (
               SELECT room_mode, room_state_timestamp FROM room_state WHERE room_id = $1
               ORDER BY room_state_timestamp DESC LIMIT 1
           ) AS room
           CROSS JOIN LATERAL (
               SELECT door_state, room_door_state_timestamp FROM room_door_state WHERE room_id = $1
               ORDER BY room_door_state_timestamp DESC LIMIT 1
           ) AS door
           CROSS JOIN LATERAL (
               SELECT smoke_state, room_smoke_state_timestamp FROM room_smoke_state WHERE room_id = $1
               ORDER BY room_smoke_state_timestamp DESC LIMIT 1
           ) AS smoke""", room_id,
    )
    if record is None:
        raise SetupError("Fixture state records missing")
    return dict(record)


async def apply_state_change(db, room_id: UUID, field: str, value: str, before: dict) -> dict:
    state_inserts = {
        "room_mode": """INSERT INTO room_state (room_id, room_mode, room_status, room_state_timestamp)
                        VALUES ($1, $2, 'online',
                                GREATEST(clock_timestamp(), $3::timestamptz + interval '1 microsecond'))""",
        "door_state": """INSERT INTO room_door_state (room_id, door_state, room_door_state_timestamp)
                         VALUES ($1, $2, GREATEST(clock_timestamp(),
                                                 $3::timestamptz + interval '1 microsecond'))""",
        "smoke_state": """INSERT INTO room_smoke_state (room_id, smoke_state, room_smoke_state_timestamp)
                          VALUES ($1, $2, GREATEST(clock_timestamp(),
                                                  $3::timestamptz + interval '1 microsecond'))""",
    }
    timestamp = TIMESTAMP_COLUMNS[field]
    await db.execute(state_inserts[field], room_id, value, before[timestamp])
    after = await read_state(db, room_id)
    expected_changes = {timestamp}
    if before[field] != value:
        expected_changes.add(field)
    changed = {key for key in before if before[key] != after[key]}
    if after[field] != value or after[timestamp] <= before[timestamp] or changed != expected_changes:
        raise SetupError(f"Unexpected state change after updating {field}")
    return after


async def apply_steps(db, edge, room_id: UUID, steps: tuple[tuple[str, str], ...],
                      state: dict, snapshot: dict, timeout: float, evidence: list) -> tuple[dict, dict]:
    for field, value in steps:
        value_changed = state[field] != value
        state = await apply_state_change(db, room_id, field, value, state)
        if value_changed:
            snapshot = await wait_for_snapshot(edge, room_id, state["room_mode"],
                                               previous_version=snapshot["state_version"], timeout=timeout)
        else:
            # Redundant same-value writes must NOT perturb composite state_version.
            snapshot = await get_snapshot(edge, room_id)
            if snapshot.get("room_id") != str(room_id) or snapshot.get("mode") != state["room_mode"]:
                raise SetupError(f"Unexpected snapshot after same-value {field} write")
        evidence.append({"field": field, "value": value, "db_state": state, "snapshot": snapshot})
    return state, snapshot


async def get_snapshot(edge: httpx.AsyncClient, room_id: UUID) -> dict:
    response = await edge.get(f"/api/commands/room/{room_id}/state-snapshot")
    response.raise_for_status()
    return response.json()


async def wait_for_snapshot(edge: httpx.AsyncClient, room_id: UUID, mode: str,
                            *, previous_version: str | None = None, timeout: float) -> dict:
    async with asyncio.timeout(timeout):
        while True:
            snapshot = await get_snapshot(edge, room_id)
            version = snapshot.get("state_version")
            if (snapshot.get("room_id") == str(room_id) and snapshot.get("mode") == mode
                    and version and version != previous_version):
                return snapshot
            await asyncio.sleep(0.1)


async def observe(broker, window: float, frames: list) -> None:
    # A healthy subscription with no matching packet is a valid observation.
    try:
        async with asyncio.timeout(window):
            async for message in broker.messages:
                frames.append({"topic": str(message.topic), "retained": bool(message.retain),
                               "body": message.payload.decode("utf-8", errors="replace")})
    except TimeoutError:
        pass


def classify(result: dict, frames: list, *, room_id: UUID, proposal_id: str, command: str,
             http_status: int) -> dict:
    execution = result.get("execution_result") or {}
    edge_status = execution.get("edge_status")
    edge_response = execution.get("edge_response")
    if isinstance(edge_response, str):
        try:
            edge_response = json.loads(edge_response)
        except ValueError:
            edge_response = None
    detail = (edge_response.get("detail") if isinstance(edge_response, dict) else None)
    reason_code = detail.get("code") if isinstance(detail, dict) else None
    command_id = edge_response.get("command_id") if isinstance(edge_response, dict) else None

    _, _, command_type, command_value = COMMANDS[command]
    live_frames = [frame for frame in frames if not frame["retained"]]
    edge_frames = 0
    backend_frames = 0
    uncorrelated = 0
    side_effect_frames = 0
    for frame in live_frames:
        try:
            envelope = json.loads(frame["body"])
            payload = envelope["payload"]
            if not isinstance(payload, dict):
                raise TypeError("Expected a command payload object")
        except (ValueError, KeyError, TypeError):
            uncorrelated += 1
            continue
        if (command == "mode_saving" and payload.get("room_id") == str(room_id)
                and payload.get("command_type") == "led_strip" and not payload.get("command_id")):
            # The Edge mode transition publishes a derived LED update on the room command topic.
            side_effect_frames += 1
        elif (payload.get("room_id"), payload.get("command_type"), payload.get("command_value")) != (
            str(room_id), command_type, command_value
        ):
            uncorrelated += 1
        elif command_id and payload.get("command_id") == command_id:
            edge_frames += 1
        elif str(payload.get("reason", "")).startswith(f"AI Recommendation {proposal_id} ("):
            backend_frames += 1
        else:
            uncorrelated += 1

    outcome = "inconclusive"
    layer = "unknown"
    if http_status == 200 and edge_status == "success" and result.get("status") == "approved":
        if edge_frames and not uncorrelated:
            outcome, layer = "dispatch", "none"
    elif http_status == 200 and not live_frames:
        if edge_status == "stale_approval" and result.get("status") == "stale" and reason_code == "STALE_APPROVAL":
            outcome, layer = "stale", "edge_state_binding"
        elif edge_status == "blocked_by_edge_interlock" and reason_code:
            outcome, layer = "blocked", "edge_fsm"
    if http_status == 400 and result.get("detail") == "Recommendation already approved" and not live_frames:
        outcome, layer, reason_code = "duplicate_blocked", "approval_lifecycle", "ALREADY_APPROVED"
    if http_status == 409 and isinstance(result.get("detail"), dict):
        reason_code = result["detail"].get("code")
        if reason_code == "APPROVAL_PAYLOAD_MISMATCH" and not live_frames:
            outcome, layer = "blocked", "backend_payload_binding"
    return {"outcome": outcome, "first_block_layer": layer, "reason_code": reason_code,
            "backend_status": result.get("status"), "edge_status": edge_status,
            "edge_command_id": command_id, "edge_frames": edge_frames,
            "backend_frames": backend_frames, "side_effect_frames": side_effect_frames,
            "uncorrelated_frames": uncorrelated}


async def create_proposal(backend, room_id: UUID, command: str, reason: str, snapshot: dict) -> dict:
    tool_name, tool_params, _, _ = COMMANDS[command]
    response = await backend.post("/api/recommendations", json={
        "room_id": str(room_id), "tool_name": tool_name, "tool_params": tool_params, "reason": reason,
    })
    response.raise_for_status()
    proposal = response.json()
    binding = proposal["tool_params"].get("_binding") or {}
    if (response.status_code != 201 or proposal.get("status") != "pending"
            or binding.get("expected_mode") != snapshot["mode"]
            or binding.get("expected_state_version") != snapshot["state_version"]
            or not binding.get("payload_hash")):
        raise SetupError("Proposal did not capture the verified baseline")
    UUID(proposal["id"])
    return proposal


async def approve_proposal(backend, broker, room_id: UUID, proposal: dict, command: str,
                           window: float, evidence: dict) -> dict:
    proposal_id = proposal["id"]
    evidence["approval_requested_at"] = datetime.now(timezone.utc)
    response = await backend.post(f"/api/recommendations/{proposal_id}/execute", json={
        "action": "approve", "payload_hash": proposal["tool_params"]["_binding"]["payload_hash"],
    })
    evidence["backend_http"] = response.status_code
    try:
        body = response.json()
    except ValueError:
        body = {"unparsed_body": response.text}
    evidence["approval_response"] = body
    frames = evidence.setdefault("mqtt", [])
    await observe(broker, window, frames)
    return {
        "backend_http": response.status_code,
        **classify(body if isinstance(body, dict) else {}, frames, room_id=room_id,
                   proposal_id=proposal_id, command=command, http_status=response.status_code),
    }


async def room_command_ids(db, room_id: UUID) -> set[str]:
    rows = await db.fetch("SELECT command_id FROM command WHERE room_id = $1", room_id)
    return {str(row["command_id"]) for row in rows}


def save_evidence(output, record, evidence):
    evidence["finished_at"] = datetime.now(timezone.utc)
    filename = f"{record.get('room_id') or uuid4().hex}.json"
    record["rejected_at"] = rejected_at(record)
    record["evidence"] = filename
    (output / filename).write_text(
        json.dumps({"result": record, **evidence}, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return record


async def run_case(args, services, scenario: Scenario, repeat: int, *, proposal_source=None) -> dict:
    edge_db, backend_db, edge, backend = services
    # The Backend telemetry bridge reserves this prefix for benchmark rooms.
    room_id = UUID("b2000000" + str(uuid4())[8:])
    case_id = scenario.case_id
    expected = scenario.predicted_outcome
    record = {"case_id": case_id, "profile": args.profile, "repeat": repeat, "room_id": str(room_id),
              "oracle": scenario.oracle, "predicted_outcome": expected,
              "entry_point": ENTRY_POINTS["e2e_approval" if proposal_source else "approval_flow"],
              "model_source": args.model_source if proposal_source else "not_used"}
    evidence = {"started_at": datetime.now(timezone.utc), "mqtt": [],
                "before_proposal_steps": [], "before_approval_steps": []}
    phase = "setup"
    try:
        async with aiomqtt.Client(args.mqtt_host, port=args.mqtt_port,
                                  username=os.getenv("BENCH_MQTT_USERNAME"),
                                  password=os.getenv("BENCH_MQTT_PASSWORD"), timeout=5) as broker:
            await broker.subscribe(f"smartcampus/v1/command/room/{room_id}", qos=1)
            await seed_room(edge_db, backend_db, room_id, scenario.initial)
            initial = await read_state(edge_db, room_id)
            if any(initial[field] != value for field, value in scenario.initial.items()):
                raise SetupError("Unexpected initial state")
            snapshot = await wait_for_snapshot(edge, room_id, initial["room_mode"], timeout=args.snapshot_timeout)
            evidence.update(initial_state=initial, initial_snapshot=snapshot)
            before, baseline = await apply_steps(
                edge_db, edge, room_id, scenario.before_proposal, initial, snapshot,
                args.snapshot_timeout, evidence["before_proposal_steps"],
            )
            evidence.update(baseline=baseline, db_before=before)

            async def obtain_proposal(command, reason, fixture_name=""):
                if proposal_source is None:
                    return await create_proposal(backend, room_id, command, reason, baseline), {}
                attempt = {}
                evidence.setdefault("agent_proposal_attempts", []).append(attempt)
                return await proposal_source(
                    args, services, broker, room_id, command, baseline, attempt, fixture_name=fixture_name,
                )

            first_command = scenario.approve_first
            duplicate = first_command == "same_proposal"
            first_proposal = None
            if first_command and not duplicate:
                first_proposal, first_metrics = await obtain_proposal(first_command, "Valid first test proposal")
                evidence["first_approval"] = {"proposal": first_proposal, **first_metrics}

            proposal, metrics = await obtain_proposal(
                scenario.command, scenario.reason, fixture_name=scenario.fixture_name,
            )
            evidence["proposal"] = proposal
            record.update(proposal_id=proposal["id"], **metrics)
            after, at_approval = before, baseline
            if first_command:
                if duplicate:
                    first_command, first_proposal = scenario.command, proposal
                    evidence["first_approval"] = {"proposal": first_proposal}
                first_evidence = evidence["first_approval"]
                first_result = await approve_proposal(
                    backend, broker, room_id, first_proposal, first_command, args.mqtt_window, first_evidence,
                )
                first_evidence["result"] = first_result
                if first_result["outcome"] != "dispatch":
                    raise SetupError("First approval did not produce a confirmed dispatch")
                if first_command == "mode_saving":
                    at_approval = await wait_for_snapshot(
                        edge, room_id, "SAVING", previous_version=baseline["state_version"],
                        timeout=args.snapshot_timeout,
                    )
                    after = await read_state(edge_db, room_id)
                    if after["room_mode"] != "SAVING":
                        raise SetupError("First command did not persist the expected room mode")
                elif await get_snapshot(edge, room_id) != baseline:
                    raise SetupError("First command unexpectedly changed the room snapshot")
                first_evidence.update(db_after=after, snapshot_after=at_approval)

            after, at_approval = await apply_steps(
                edge_db, edge, room_id, scenario.before_approval, after, at_approval,
                args.snapshot_timeout, evidence["before_approval_steps"],
            )
            evidence.update(db_at_approval=after, at_approval=at_approval)
            if await get_snapshot(edge, room_id) != at_approval:
                raise SetupError("State moved again before approval")

            if duplicate:
                commands_before = await room_command_ids(edge_db, room_id)
                evidence["commands_before_retry"] = sorted(commands_before)
                if commands_before != {first_result["edge_command_id"]}:
                    raise SetupError("Expected exactly one tracked Edge command before retry")

            phase = "approval"
            record.update(await approve_proposal(
                backend, broker, room_id, proposal, scenario.command, args.mqtt_window, evidence,
            ))
            if duplicate:
                commands_after = await room_command_ids(edge_db, room_id)
                evidence["commands_after_retry"] = sorted(commands_after)
                record["new_edge_commands"] = len(commands_after - commands_before)
                if record["outcome"] == "duplicate_blocked" and commands_after != commands_before:
                    record.update(outcome="inconclusive", first_block_layer="unknown")
            if record["outcome"] == "inconclusive":
                record["run_status"] = "inconclusive"
            else:
                record["run_status"] = "observed"
                record["matches_prediction"] = record["outcome"] == expected
    except AgentStageError as exc:
        record.update(run_status="inconclusive", reason_code=str(exc))
    except (SetupError, TimeoutError, asyncpg.PostgresError, aiomqtt.MqttError,
            httpx.HTTPError, ValueError, KeyError, OSError) as exc:
        record["run_status"] = "setup_error" if phase == "setup" else "inconclusive"
        record["reason_code"] = type(exc).__name__
        evidence["error"] = ({"type": type(exc).__name__, "message": str(exc)}
                             if isinstance(exc, SetupError) else {"type": type(exc).__name__})
    outcome = record.get("outcome")
    if outcome and outcome != "inconclusive":
        record["policy_agreement"] = outcome in {
            "allow": {"dispatch"},
            "reject_stale": {"stale", "blocked"},
            "no_extra_dispatch": {"duplicate_blocked"},
        }[scenario.oracle]
    return save_evidence(args.output, record, evidence)


def local_url(value: str, schemes: set[str]) -> str:
    parts = urlsplit(value)
    if parts.scheme not in schemes or parts.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise SetupError("Approval runner accepts loopback endpoints only")
    return value


async def run(args, cases: list[Scenario]) -> int:
    env_names = ("BENCH_EDGE_DSN", "BENCH_BACKEND_DSN", "BENCH_APPROVAL_TOKEN")
    if any(not os.getenv(key) for key in env_names):
        raise SetupError(f"Set {', '.join(env_names)} for the isolated stack")
    edge_dsn, backend_dsn = (local_url(os.environ[key], {"postgresql", "postgres"}) for key in env_names[:2])
    if edge_dsn == backend_dsn:
        raise SetupError("Use distinct test databases for Edge and Backend")
    args.output.mkdir(parents=True, exist_ok=False)
    failed = False
    async with AsyncExitStack() as stack:
        edge = await stack.enter_async_context(httpx.AsyncClient(
            base_url=local_url(args.edge_url, {"http", "https"}), timeout=15, trust_env=False,
        ))
        backend = await stack.enter_async_context(httpx.AsyncClient(
            base_url=local_url(args.backend_url, {"http", "https"}), timeout=15, trust_env=False,
            headers={"Authorization": f"Bearer {os.environ['BENCH_APPROVAL_TOKEN']}"},
        ))
        effective = await backend.get("/api/recommendations/hitl/status")
        effective.raise_for_status()
        if effective.json().get("hitl_enabled") is not True:
            raise SetupError("Backend HITL is not enabled")
        edge_db = await asyncpg.connect(edge_dsn, timeout=5, command_timeout=10)
        stack.push_async_callback(edge_db.close)
        backend_db = await asyncpg.connect(backend_dsn, timeout=5, command_timeout=10)
        stack.push_async_callback(backend_db.close)
        with (args.output / "results.csv").open("x", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=RAW_FIELDS)
            writer.writeheader()
            for repeat in range(1, args.repeat + 1):
                for scenario in cases:
                    row = await run_case(args, (edge_db, backend_db, edge, backend), scenario, repeat)
                    writer.writerow(row)
                    file.flush()
                    print(scenario.case_id, args.profile, row["run_status"], row.get("outcome", "see evidence"))
                    failed |= not row.get("matches_prediction", False)
    print(args.output / "results.csv")
    return int(failed)


def run_asyncio(coro):
    """Run an async coroutine using SelectorEventLoop on Windows for aiomqtt compatibility."""
    if sys.platform == "win32":
        if sys.version_info >= (3, 12):
            return asyncio.run(coro, loop_factory=asyncio.SelectorEventLoop)
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    return asyncio.run(coro)


def main(*, default_manifest: Path = ROOT / "experiment/approval_cases.csv",
         default_cases: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("M3", "M4"), required=True)
    parser.add_argument("--project", required=True, help="Compose project of the isolated stack")
    parser.add_argument("--compose-file", type=Path, default=ROOT / "docker-compose.yml")
    parser.add_argument("--manifest", type=Path, default=default_manifest)
    parser.add_argument("--fixtures", type=Path, default=ROOT / "experiment/approval_fixtures.json")
    parser.add_argument("--case", action="append", dest="cases")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--backend-url", default="http://127.0.0.1:8001")
    parser.add_argument("--edge-url", default="http://127.0.0.1:8000")
    parser.add_argument("--mqtt-host", choices=("localhost", "127.0.0.1", "::1"), default="127.0.0.1")
    parser.add_argument("--mqtt-port", type=int, default=1883)
    parser.add_argument("--snapshot-timeout", type=float, default=5)
    parser.add_argument("--mqtt-window", type=float, default=2)
    parser.add_argument("--isolated-test-stack", action="store_true",
                        help="Confirm the databases and broker belong to a test stack with no real subscribers")
    args = parser.parse_args()
    if not args.isolated_test_stack:
        parser.error("--isolated-test-stack is required")
    if (args.repeat < 1 or not 1 <= args.mqtt_port <= 65535
            or any(not math.isfinite(value) or value <= 0
                   for value in (args.snapshot_timeout, args.mqtt_window))):
        parser.error("Repeat, port and timeouts must be valid positive values")
    args.compose_file = args.compose_file.resolve()
    if args.output is None:
        args.output = ROOT / "benchmark_local/runs" / f"{args.profile}-{uuid4().hex}"
    try:
        cases = read_cases(args.manifest, args.fixtures, args.profile, args.cases or default_cases)
        verify_compose(args)
        return run_asyncio(run(args, cases))
    except SetupError as exc:
        parser.exit(2, f"Preflight failed: {exc}\n")
    except (OSError, subprocess.TimeoutExpired, asyncpg.PostgresError, httpx.HTTPError, ValueError) as exc:
        parser.exit(2, f"Preflight failed: {type(exc).__name__}\n")


if __name__ == "__main__":
    raise SystemExit(main())
