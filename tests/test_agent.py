"""
Unit tests for the ADK + Gemini agent layer.

Gemini/ADK calls are mocked. No live API key is required.
"""

import typing
from unittest.mock import patch

from src.agent import (
    AgentCommuteRequest,
    AgentRecommendation,
    build_adk_agent,
    ground_recommendation,
    parse_intent_from_text,
    recommendation_from_planner,
    run_commute_agent,
)
from src.agent.config import FALLBACK_NOTICE
from src.agent.planner import MODE_ADK_GEMINI, MODE_DETERMINISTIC_FALLBACK
from src.agent import tools as agent_tools
from src.decision_engine.models import RouteCandidate, UserPreferences, EvaluationResult
from src.planner.models import CommuteRequest, PlannerResult


def _candidate(**overrides) -> RouteCandidate:
    defaults = dict(
        route_id="maps_drive_0",
        mode="cab",
        travel_time_minutes=32.0,
        cost=350.0,
        walking_minutes=2.0,
        transfers=0,
        congestion_score=0.40,
        reliability_score=0.80,
        disruption_risk=0.10,
        historical_mobility_signal=None,
    )
    defaults.update(overrides)
    return RouteCandidate(**defaults)


def _planner_result(routes=None, recommended=None, historical=False) -> PlannerResult:
    routes = routes or [
        _candidate(),
        _candidate(route_id="maps_transit_0", mode="metro", travel_time_minutes=55.0, cost=25.0),
    ]
    recommended = recommended or routes[0]
    evaluation = EvaluationResult(
        recommended_route=recommended,
        ranked_routes=[],
        score=10.0,
        reason_codes=["FASTEST", "LOW_CONGESTION"],
    )
    from src.decision_engine.models import ScoredRoute
    if not evaluation.ranked_routes:
        evaluation.ranked_routes = [
            ScoredRoute(
                route=r,
                final_score=10.0 - i,
                reason_codes=["FASTEST"] if r.route_id == recommended.route_id else [],
            )
            for i, r in enumerate(routes)
        ]
    return PlannerResult(
        request=CommuteRequest(
            user_id="user-1",
            origin="Electronic City",
            destination="Koramangala",
            departure_time="2024-09-06T08:00:00Z",
        ),
        routes=routes,
        evaluation=evaluation,
        data_sources=["google_maps_routes"] + (["uber_movement_xgboost"] if historical else []),
        historical_signal_used=historical,
        warnings=[],
    )


def test_agent_imports_successfully():
    import src.agent as agent_pkg
    import src.agent.planner as planner_mod
    import src.agent.tools as tools_mod
    import src.agent.schemas as schemas_mod
    assert hasattr(agent_pkg, "run_commute_agent")
    assert hasattr(planner_mod, "build_adk_agent")
    assert callable(tools_mod.plan_commute)
    assert schemas_mod.AgentRecommendation is AgentRecommendation


def test_schemas_validate_and_serialize():
    req = AgentCommuteRequest(
        user_id="u1",
        origin="A",
        destination="B",
        preferences=UserPreferences(avoid_heavy_traffic=True, max_walking_minutes=10.0),
    )
    commute = req.to_commute_request()
    assert commute.origin == "A"
    assert commute.preferences.avoid_heavy_traffic is True
    assert "origin" in req.to_dict()

    pr = _planner_result()
    rec = recommendation_from_planner(pr, "test explanation")
    assert rec.recommended_route.route_id == "maps_drive_0"
    assert rec.estimated_time == 32.0
    assert rec.explanation == "test explanation"
    payload = rec.to_dict()
    assert payload["reason_codes"] == ["FASTEST", "LOW_CONGESTION"]


@patch("src.agent.tools._plan_commute")
def test_tool_wrappers_work(mock_plan):
    mock_plan.return_value = _planner_result()
    payload = agent_tools.plan_commute(
        user_id="u1",
        origin="Electronic City",
        destination="Koramangala",
        avoid_heavy_traffic=True,
        max_walking_minutes=10.0,
    )
    assert payload["tool"] == "plan_commute"
    mock_plan.assert_called_once()

    weather = agent_tools.get_weather("Bengaluru")
    assert weather["available"] is False
    assert weather["reason"] == "not_configured"

    prefs = agent_tools.get_user_preferences("u1")
    assert prefs["available"] is False


def test_all_adk_tool_declarations_succeed():
    from google.adk.tools.function_tool import FunctionTool

    tools = agent_tools.adk_tool_functions()
    assert len(tools) == 12
    for fn in tools:
        decl = FunctionTool(fn)._get_declaration()
        assert decl is not None
        assert decl.name == fn.__name__


def test_plan_commute_declaration_succeeds():
    from google.adk.tools.function_tool import FunctionTool
    decl = FunctionTool(agent_tools.plan_commute)._get_declaration()
    assert decl.name == "plan_commute"


def test_get_routes_declaration_succeeds():
    from google.adk.tools.function_tool import FunctionTool
    decl = FunctionTool(agent_tools.get_routes)._get_declaration()
    assert decl.name == "get_routes"


def test_evaluate_routes_declaration_succeeds():
    from google.adk.tools.function_tool import FunctionTool
    decl = FunctionTool(agent_tools.evaluate_routes)._get_declaration()
    assert decl.name == "evaluate_routes"


def test_adk_tool_signatures_have_no_complex_optional_nested_hints():
    """ADK boundary must not expose Optional/Union/List[T]/Dict[K,V]."""
    allowed = {str, int, float, bool, dict, type(None)}
    for fn in agent_tools.adk_tool_functions():
        hints = typing.get_type_hints(fn)
        for name, hint in hints.items():
            if name == "return":
                assert hint is dict or hint == dict
                continue
            origin = typing.get_origin(hint)
            assert origin is None, f"{fn.__name__}.{name} has nested origin {origin}"
            assert hint in allowed, f"{fn.__name__}.{name} has unsafe hint {hint}"


def test_parse_intent_demo_phrase():
    text = (
        "Find the best way from Electronic City to Koramangala at 8 AM. "
        "Avoid heavy traffic and keep walking under 10 minutes."
    )
    intent = parse_intent_from_text(text)
    assert intent["origin"] == "Electronic City"
    assert intent["destination"] == "Koramangala"
    assert intent["departure_time"] == "2024-09-06T08:00:00Z"
    assert intent["avoid_heavy_traffic"] is True
    assert intent["max_walking_minutes"] == 10.0
    assert intent["origin_zone"] is None
    assert intent["destination_zone"] is None


@patch("src.agent.planner._plan_commute")
@patch.dict("os.environ", {"GOOGLE_GENAI_API_KEY": "", "GEMINI_API_KEY": "", "GOOGLE_API_KEY": ""}, clear=False)
def test_missing_gemini_credentials_triggers_fallback(mock_plan):
    mock_plan.return_value = _planner_result()
    result = run_commute_agent(
        "Find the best way from Electronic City to Koramangala at 8 AM. "
        "Avoid heavy traffic and keep walking under 10 minutes.",
        invoke_gemini=True,
    )
    assert result.gemini_available is False
    assert result.gemini_invoked is False
    assert result.adk_invoked is False
    assert result.mode == MODE_DETERMINISTIC_FALLBACK
    assert result.recommendation.explanation == FALLBACK_NOTICE
    mock_plan.assert_called_once()


@patch("src.agent.planner._plan_commute")
def test_plan_commute_is_called_and_recommendation_authoritative(mock_plan):
    pr = _planner_result()
    mock_plan.return_value = pr
    with patch.dict("os.environ", {"GOOGLE_GENAI_API_KEY": ""}, clear=False):
        result = run_commute_agent(
            "from Electronic City to Koramangala at 8 AM",
            invoke_gemini=False,
        )
    assert "plan_commute" in result.tools_selected
    assert result.planner_result is pr
    assert result.recommendation.recommended_route.route_id == "maps_drive_0"
    assert result.recommendation.estimated_time == 32.0
    assert result.recommendation.estimated_cost == 350.0
    assert result.recommendation.data_sources == ["google_maps_routes"]
    assert result.recommendation.historical_signal_used is False


@patch("src.agent.planner._plan_commute")
def test_unavailable_context_tools_remain_explicit(mock_plan):
    mock_plan.return_value = _planner_result()
    with patch.dict("os.environ", {"GOOGLE_GENAI_API_KEY": ""}, clear=False):
        result = run_commute_agent("from A to B at 9 AM", invoke_gemini=False)
    assert "get_weather" in result.tools_selected
    assert "get_disruptions" in result.tools_selected
    assert "get_commute_history" in result.tools_selected
    assert any("weather unavailable" in w for w in result.recommendation.warnings)
    assert any("disruptions unavailable" in w for w in result.recommendation.warnings)


@patch("src.agent.planner._plan_commute")
def test_historical_ml_only_when_explicit_ward_ids(mock_plan):
    mock_plan.return_value = _planner_result(historical=False)
    with patch.dict("os.environ", {"GOOGLE_GENAI_API_KEY": ""}, clear=False):
        no_zones = run_commute_agent(
            "from Electronic City to Koramangala at 8 AM",
            invoke_gemini=False,
        )
    assert no_zones.recommendation.historical_signal_used is False
    assert no_zones.parsed_intent["origin_zone"] is None

    mock_plan.return_value = _planner_result(historical=True)
    with patch.dict("os.environ", {"GOOGLE_GENAI_API_KEY": ""}, clear=False):
        with_zones = run_commute_agent(
            "from Electronic City to Koramangala at 8 AM. "
            "origin_zone=12 destination_zone=84",
            invoke_gemini=False,
        )
    assert with_zones.parsed_intent["origin_zone"] == 12
    assert with_zones.parsed_intent["destination_zone"] == 84
    assert with_zones.recommendation.historical_signal_used is True
    assert "uber_movement_xgboost" in with_zones.recommendation.data_sources


def test_gemini_cannot_override_deterministic_route():
    pr = _planner_result(recommended=_candidate(route_id="maps_drive_0"))
    grounded = ground_recommendation(
        pr,
        explanation="fake llm text",
        conflicting={
            "recommended_route_id": "invented_route_99",
            "estimated_time": 999.0,
            "estimated_cost": 1.0,
            "reason_codes": ["INVENTED"],
        },
    )
    assert grounded.recommended_route.route_id == "maps_drive_0"
    assert grounded.estimated_time == 32.0
    assert grounded.estimated_cost == 350.0
    assert grounded.reason_codes == ["FASTEST", "LOW_CONGESTION"]
    assert any("discarded conflicting" in w for w in grounded.warnings)


@patch("src.agent.planner._plan_commute")
def test_no_fabricated_mobility_facts_in_fallback(mock_plan):
    mock_plan.return_value = _planner_result()
    with patch.dict(
        "os.environ",
        {"GOOGLE_GENAI_API_KEY": "", "GEMINI_API_KEY": "", "GOOGLE_API_KEY": ""},
        clear=False,
    ):
        result = run_commute_agent(
            "What is the weather and traffic from X to Y?",
            invoke_gemini=True,
        )
    assert result.recommendation.explanation == FALLBACK_NOTICE
    assert "sunny" not in result.recommendation.explanation.lower()
    assert "heavy rain" not in result.recommendation.explanation.lower()
    weather = agent_tools.get_weather("X")
    assert weather["available"] is False


def test_build_adk_agent_uses_tools_and_system_instruction():
    agent = build_adk_agent(model="gemini-2.0-flash")
    assert agent.name == "commute_planner_agent"
    assert "deterministic" in agent.instruction.lower() or "Never invent" in agent.instruction
    assert len(agent.tools) == 12


@patch("src.agent.planner._invoke_adk_explanation")
@patch("src.agent.planner._plan_commute")
@patch("src.agent.planner.gemini_credentials_available", return_value=True)
@patch("src.agent.planner.adk_importable", return_value=True)
def test_mocked_gemini_path_still_grounds_planner(
    _adk_ok, _creds, mock_plan, mock_explain
):
    pr = _planner_result()
    mock_plan.return_value = pr
    mock_explain.return_value = (
        "Based on the planner result, maps_drive_0 is recommended.",
        True,
        "",
    )
    result = run_commute_agent(
        "from Electronic City to Koramangala at 8 AM",
        invoke_gemini=True,
        conflicting_llm_fields={
            "recommended_route_id": "llm_override_route",
            "estimated_time": 1.0,
        },
    )
    assert result.mode == MODE_ADK_GEMINI
    assert result.gemini_invoked is True
    assert result.adk_invoked is True
    assert result.recommendation.recommended_route.route_id == "maps_drive_0"
    assert result.recommendation.estimated_time == 32.0
    assert any("discarded conflicting" in w for w in result.recommendation.warnings)
    mock_explain.assert_called_once()


@patch("src.agent.planner._invoke_adk_explanation")
@patch("src.agent.planner._plan_commute")
@patch("src.agent.planner.gemini_credentials_available", return_value=True)
@patch("src.agent.planner.adk_importable", return_value=True)
def test_adk_empty_response_not_reported_as_gemini_success(
    _adk_ok, _creds, mock_plan, mock_explain
):
    mock_plan.return_value = _planner_result()
    mock_explain.return_value = (
        "",
        False,
        "ADK execution failed: no events returned",
    )
    result = run_commute_agent(
        "from Electronic City to Koramangala at 8 AM",
        invoke_gemini=True,
    )
    assert result.mode == MODE_DETERMINISTIC_FALLBACK
    assert result.gemini_invoked is False
    assert result.adk_invoked is False
    assert result.recommendation.explanation == FALLBACK_NOTICE
    assert any("ADK execution failed" in w for w in result.recommendation.warnings)
    assert result.recommendation.recommended_route.route_id == "maps_drive_0"
    assert result.recommendation.estimated_time == 32.0
