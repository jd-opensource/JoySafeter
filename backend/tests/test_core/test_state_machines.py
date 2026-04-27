import pytest
from app.core.state_machines import (
    AGENT_SM, VERSION_SM, RELEASE_SM, RUN_SM, EXECUTION_SM, TASK_SM,
    InvalidTransition, RUN_TO_TASK_SYNC,
)


class TestStateMachineEngine:
    def test_valid_transition(self):
        RUN_SM.validate("pending", "running")

    def test_invalid_transition_raises(self):
        with pytest.raises(InvalidTransition) as exc_info:
            RUN_SM.validate("succeeded", "running")
        assert "succeeded" in str(exc_info.value)
        assert "running" in str(exc_info.value)

    def test_terminal_check(self):
        assert RUN_SM.is_terminal("succeeded")
        assert RUN_SM.is_terminal("failed")
        assert not RUN_SM.is_terminal("running")

    def test_unknown_source_raises(self):
        with pytest.raises(InvalidTransition):
            RUN_SM.validate("nonexistent", "running")


class TestAgentStateMachine:
    def test_draft_to_active(self):
        AGENT_SM.validate("draft", "active")

    def test_active_to_draft(self):
        AGENT_SM.validate("active", "draft")

    def test_active_to_archived(self):
        AGENT_SM.validate("active", "archived")

    def test_draft_to_archived(self):
        AGENT_SM.validate("draft", "archived")

    def test_archived_to_draft(self):
        AGENT_SM.validate("archived", "draft")

    def test_archived_to_active_is_invalid(self):
        with pytest.raises(InvalidTransition):
            AGENT_SM.validate("archived", "active")


class TestRunStateMachine:
    def test_pending_can_run_or_cancel(self):
        RUN_SM.validate("pending", "running")
        RUN_SM.validate("pending", "cancelled")

    def test_running_terminal_transitions(self):
        for target in ("succeeded", "failed", "cancelled"):
            RUN_SM.validate("running", target)

    def test_terminal_states_have_no_exits(self):
        for terminal in ("succeeded", "failed", "cancelled"):
            with pytest.raises(InvalidTransition):
                RUN_SM.validate(terminal, "running")


class TestExecutionStateMachine:
    def test_full_happy_path(self):
        EXECUTION_SM.validate("pending", "dispatched")
        EXECUTION_SM.validate("dispatched", "running")
        EXECUTION_SM.validate("running", "succeeded")

    def test_approval_wait_round_trip(self):
        EXECUTION_SM.validate("running", "approval_wait")
        EXECUTION_SM.validate("approval_wait", "running")

    def test_any_active_state_can_cancel(self):
        for state in ("pending", "dispatched", "running", "approval_wait"):
            EXECUTION_SM.validate(state, "cancelled")


class TestTaskStateMachine:
    def test_full_lifecycle(self):
        TASK_SM.validate("backlog", "todo")
        TASK_SM.validate("todo", "in_progress")
        TASK_SM.validate("in_progress", "done")

    def test_reopen_from_done(self):
        TASK_SM.validate("done", "backlog")

    def test_reopen_from_cancelled(self):
        TASK_SM.validate("cancelled", "backlog")

    def test_cannot_skip_to_done_from_backlog(self):
        with pytest.raises(InvalidTransition):
            TASK_SM.validate("backlog", "done")

    def test_review_cycle(self):
        TASK_SM.validate("in_progress", "in_review")
        TASK_SM.validate("in_review", "in_progress")
        TASK_SM.validate("in_review", "done")


class TestRunToTaskSync:
    def test_all_run_terminals_have_mapping(self):
        for terminal in ("succeeded", "failed", "cancelled"):
            assert terminal in RUN_TO_TASK_SYNC

    def test_sync_values_are_valid_task_statuses(self):
        for target in RUN_TO_TASK_SYNC.values():
            assert target in TASK_SM.all_statuses


class TestAllStateMachinesCoherent:
    @pytest.mark.parametrize("sm", [AGENT_SM, VERSION_SM, RELEASE_SM, RUN_SM, EXECUTION_SM, TASK_SM])
    def test_all_target_states_exist_as_source(self, sm):
        """Every state that is a transition target must also be defined as a source."""
        all_targets = set()
        for targets in sm._transitions.values():
            all_targets |= targets
        missing = all_targets - sm.all_statuses
        assert missing == set(), f"{sm.name}: target states {missing} not defined as source states"

    @pytest.mark.parametrize("sm", [AGENT_SM, VERSION_SM, RELEASE_SM, RUN_SM, EXECUTION_SM, TASK_SM])
    def test_terminal_states_have_empty_transitions(self, sm):
        """Terminal states should have no outbound transitions."""
        for terminal in sm._terminal:
            assert sm._transitions.get(terminal, set()) == set(), \
                f"{sm.name}: terminal state '{terminal}' has outbound transitions"


class TestTerminalStateGuard:
    """Verify StateTransitionSubscriber rejects terminal statuses via STATUS_CHANGE."""

    def test_status_change_rejects_terminal_statuses(self):
        import asyncio
        import uuid
        from app.core.events.envelope import ExecutionEventEnvelope
        from app.core.events.event_types import ExecutionEventType
        from app.core.events.subscribers.state_transition import StateTransitionSubscriber
        from unittest.mock import AsyncMock

        sub = StateTransitionSubscriber()
        db = AsyncMock()

        for terminal in ("succeeded", "failed", "cancelled"):
            envelope = ExecutionEventEnvelope(
                execution_id=uuid.uuid4(),
                run_id=uuid.uuid4(),
                workspace_id=uuid.uuid4(),
                event_type=ExecutionEventType.EXECUTION_STATUS_CHANGE,
                payload={"status": terminal},
                target_status=terminal,
            )
            with pytest.raises(RuntimeError, match="must use EXECUTION_COMPLETED"):
                asyncio.get_event_loop().run_until_complete(sub.handle(envelope, db=db))
