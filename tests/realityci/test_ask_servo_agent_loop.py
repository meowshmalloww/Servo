from __future__ import annotations

from tools.realityci.ask_servo.agent_loop import AskAgentRequest, run_agent_goal
from tools.realityci.ask_servo.tools import AskToolCall, AskToolName


def test_agent_loop_inspects_executes_and_verifies_campaign_evidence() -> None:
    calls: list[AskToolCall] = []

    def planner(_request):
        return (
            "gemini",
            AskToolCall(
                tool=AskToolName.RUN_TO_COMPLETION,
                explanation="Run the durable campaign graph.",
            ),
        )

    def executor(call: AskToolCall):
        calls.append(call)
        if call.tool == AskToolName.GET_CAMPAIGN_STATE:
            return {
                "tool": call.tool.value,
                "message": "Campaign status loaded.",
                "result": {
                    "campaign_id": call.campaign_id,
                    "state": "pending" if len(calls) == 1 else "completed_rejected",
                    "terminal": len(calls) != 1,
                },
            }
        if call.tool == AskToolName.RUN_TO_COMPLETION:
            return {
                "tool": call.tool.value,
                "message": "Campaign completed through deterministic gates.",
                "result": {
                    "campaign_id": call.campaign_id,
                    "state": "completed_rejected",
                    "terminal": True,
                    "orchestrator": "google-adk/2.7.1",
                    "adk_event_count": 13,
                    "adk_session_id": "servo-campaign-test",
                    "adk_steps": [{"node": "step_00_pending", "to": "baseline_running"}],
                },
            }
        if call.tool == AskToolName.GET_CAMPAIGN_EVENTS:
            return {
                "tool": call.tool.value,
                "message": "Campaign events loaded.",
                "result": {
                    "events": [
                        {
                            "event_type": "CHECKPOINT_REJECTED",
                            "sequence": 31,
                            "record_id": "evt-0123456789abcdef",
                            "content_hash": "sha256:" + "a" * 64,
                        }
                    ]
                },
            }
        if call.tool == AskToolName.GET_ARTIFACTS:
            return {
                "tool": call.tool.value,
                "message": "Campaign artifacts loaded.",
                "result": {"artifacts": [{"artifact_id": "artifact-1"}]},
            }
        raise AssertionError(f"unexpected tool: {call.tool}")

    result = run_agent_goal(
        AskAgentRequest(
            prompt="Run the selected campaign through the agentic loop",
            provider="gemini",
            campaign_id="cam-0123456789abcdef",
        ),
        run_id="askrun-0123456789abcdef",
        planner=planner,
        executor=executor,
    )

    assert result["status"] == "completed"
    assert result["provider"] == "gemini"
    assert [call.tool for call in calls] == [
        AskToolName.GET_CAMPAIGN_STATE,
        AskToolName.RUN_TO_COMPLETION,
        AskToolName.GET_CAMPAIGN_STATE,
        AskToolName.GET_CAMPAIGN_EVENTS,
        AskToolName.GET_ARTIFACTS,
    ]
    assert result["evidence"]["state"] == "completed_rejected"
    assert result["evidence"]["event_count"] == 1
    assert result["evidence"]["artifact_count"] == 1
    assert result["evidence"]["latest_event"]["event_type"] == "CHECKPOINT_REJECTED"
    assert all(entry["status"] == "completed" for entry in result["trace"])


def test_agent_loop_records_unsupported_action_as_blocked_not_success() -> None:
    class BlockedAction(RuntimeError):
        detail = "Ask Servo tool is not wired: delete_world"

    def planner(_request):
        return (
            "gemini",
            AskToolCall(
                tool=AskToolName.DELETE_WORLD,
                world_id="world-test",
                explanation="Requested destructive action.",
            ),
        )

    def executor(call: AskToolCall):
        if call.tool == AskToolName.GET_WORLD_DETAILS:
            return {
                "tool": call.tool.value,
                "message": "World manifest loaded.",
                "result": {"world_id": "world-test"},
            }
        raise BlockedAction()

    result = run_agent_goal(
        AskAgentRequest(
            prompt="Delete this world",
            provider="gemini",
            world_id="world-test",
        ),
        run_id="askrun-fedcba9876543210",
        planner=planner,
        executor=executor,
    )

    assert result["status"] == "blocked"
    assert "not wired" in result["message"]
    assert result["trace"][-1]["status"] == "blocked"
    assert "result" not in result


def test_agent_loop_redacts_pasted_credentials_from_receipt_goal() -> None:
    def planner(_request):
        return (
            "deterministic",
            AskToolCall(
                tool=AskToolName.LIST_CAMPAIGNS,
                explanation="Read campaigns.",
            ),
        )

    def executor(call: AskToolCall):
        return {
            "tool": call.tool.value,
            "message": "Campaigns loaded.",
            "result": {"campaigns": []},
        }

    result = run_agent_goal(
        AskAgentRequest(
            prompt="List campaigns api_key=sk-supersecret0123456789",
            provider="deterministic",
        ),
        run_id="askrun-1111111111111111",
        planner=planner,
        executor=executor,
    )

    assert "supersecret" not in result["goal"]
    assert "[REDACTED]" in result["goal"]
