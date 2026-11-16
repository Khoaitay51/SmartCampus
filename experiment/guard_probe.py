"""Run a single offline policy or data-contract fixture inside the target service."""
import argparse
import json


def edge_fsm(inputs):
    from feature.command.interlock import InterlockViolation, check_room_command

    try:
        check_room_command(*inputs)
    except InterlockViolation as error:
        return {"outcome": "policy_denied", "first_block_layer": "edge_fsm", "reason_code": error.code}
    return {"outcome": "policy_allowed"}


def autonomy():
    from app.campus.autonomy import decide_autonomy

    can_auto, status, _, requires_confirmation = decide_autonomy("set_mode", 0.95, hitl_active=True)
    return {
        "outcome": "approval_required" if status == "pending" and requires_confirmation and not can_auto
        else "unexpected_routing",
        "routing_status": status,
    }


def payload_contract(*, equivalent):
    from app.campus.binding import compute_payload_hash, verify_binding, with_binding

    room = "b2000000-0000-4000-8000-000000000001"
    first = {"state": "on"}
    second = {"status": "on"} if equivalent else {"state": "off"}
    proposal = with_binding(room, "set_fan", first, "LECTURE", "fixture-v1")
    compared_hash, compared = compute_payload_hash(room, "set_fan", second)
    matched, reason = verify_binding(room, "set_fan", proposal, client_hash=compared_hash)
    result = {"outcome": "contract_match" if matched else "contract_mismatch",
              "verifier_reason": reason, "compared_canonical_payload": compared}
    if not matched:
        result.update(first_block_layer="backend_payload_binding", reason_code=reason)
    return result


def state_contract(mode, version):
    from feature.command.interlock import StaleApprovalError, check_expected_state

    try:
        check_expected_state("LECTURE", "fixture-v1", mode, version, source="admin_hitl")
    except StaleApprovalError as error:
        return {"outcome": "metadata_rejected", "first_block_layer": "edge_state_binding",
                "reason_code": "MISSING_STATE_METADATA", "guard_message": str(error)}
    return {"outcome": "contract_ok" if mode and version else "partial_binding_accepted",
            "fixture_has_both_fields": bool(mode and version)}


def notification_tool_policy(event_name, tool_name):
    from app.agent.prompts import find_action_policy_violations
    from app.schemas.events import EventType

    violations = find_action_policy_violations(EventType[event_name], tool_name)
    result = {"outcome": "policy_denied" if violations else "policy_allowed",
              "notification_event_type": event_name, "fixture_tool": tool_name}
    if violations:
        result.update(first_block_layer="prompt_guard", reason_code="ACTION_TOOL_POLICY")
    return result


# These inputs exist only in this offline process. The probe never dispatches a command.
FSM_FIXTURES = {
    "exam_invariant_labeled_fixture": ("EXAM", "door", "unlocked", "admin_hitl"),
    "sop_conflict_labeled_fixture": ("EMERGENCY", "door", "locked", "admin_hitl"),
    "sop_consistent_labeled_fixture": ("EMERGENCY", "fan", "on", "admin_hitl"),
    "autonomy_invariant_labeled_fixture": ("LECTURE", "mode", "saving", "ai_agent"),
    "authorized_test_fan_fixture": ("LECTURE", "fan", "on", "ai_agent"),
}
STATE_FIXTURES = {
    "binding_metadata_complete": ("LECTURE", "fixture-v1"),
    "binding_metadata_absent": (None, None),
    "binding_single_field": ("LECTURE", None),
}
PAYLOAD_FIXTURES = {"canonical_payload_equal": True, "distinct_test_fan_records": False}
NOTIFICATION_POLICY_FIXTURES = {
    "temperature_notification_expected_fan": ("TEMPERATURE_ANOMALY", "set_fan"),
    "temperature_notification_unrelated_mode": ("TEMPERATURE_ANOMALY", "set_mode"),
    "rfid_notification_unrelated_fan": ("RFID_UNKNOWN", "set_fan"),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture")
    fixture = parser.parse_args().fixture
    if fixture in FSM_FIXTURES:
        result = edge_fsm(FSM_FIXTURES[fixture])
    elif fixture in STATE_FIXTURES:
        result = state_contract(*STATE_FIXTURES[fixture])
    elif fixture in PAYLOAD_FIXTURES:
        result = payload_contract(equivalent=PAYLOAD_FIXTURES[fixture])
    elif fixture in NOTIFICATION_POLICY_FIXTURES:
        result = notification_tool_policy(*NOTIFICATION_POLICY_FIXTURES[fixture])
    elif fixture == "mode_change_waits_for_human":
        result = autonomy()
    else:
        parser.error("Unknown offline fixture")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
