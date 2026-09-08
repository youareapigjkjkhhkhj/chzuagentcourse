from services import platform_intelligence


def test_control_tower_snapshot_contains_enterprise_sections():
    snapshot = platform_intelligence.get_control_tower_snapshot()

    assert snapshot["headline"]["platform_name"] == "Atlas AI Control Tower"
    assert len(snapshot["priority_recommendations"]) >= 1
    assert len(snapshot["replenishment_candidates"]) >= 1
    assert len(snapshot["warehouse_network"]) >= 1


def test_scenario_lab_contains_multiple_scenarios():
    scenarios = platform_intelligence.get_scenario_lab()

    assert scenarios["simulation_window"]
    assert len(scenarios["scenarios"]) == 3


def test_governance_hub_has_guardrails_and_registry():
    governance = platform_intelligence.get_governance_hub()

    assert governance["policy_posture"] == "human-supervised autonomy"
    assert len(governance["guardrails"]) >= 1
    assert len(governance["agent_registry"]) == 5
