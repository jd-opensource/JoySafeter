"""
CTF Session Storage Module

Provides dataclasses and storage for CTF-specific session context:
- CtfSession: Main session state with CTF mode flags
- UserHint: User-provided solution ideas with status tracking
- ReferenceHit: Retrieved items from CTF knowledge sources
- AttemptStep: Recorded shell/Python actions with outcomes
"""

from dataclasses import dataclass, field
from datetime import datetime
from threading import Lock
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from app.dynamic_agent.core.constants import (
    CtfAttemptOutcome,
    CtfDetectionSource,
    CtfHintStatus,
    CtfReferenceSource,
    CtfRiskLevel,
    CtfSessionStatus,
    CtfToolType,
)


@dataclass
class UserHint:
    """
    User-provided solution idea with status tracking.

    Each hint must resolve to 'applied' or 'skipped' before session closes.
    """

    hint_id: UUID = field(default_factory=uuid4)
    session_id: Optional[UUID] = None
    content: str = ""  # Required, <=1024 chars
    order: int = 0  # Determines application sequence
    status: CtfHintStatus = CtfHintStatus.QUEUED
    skip_reason: Optional[str] = None  # Required when status=skipped; <256 chars
    created_at: datetime = field(default_factory=datetime.now)

    def apply(self) -> None:
        """Mark hint as applied."""
        self.status = CtfHintStatus.APPLIED

    def skip(self, reason: str) -> None:
        """Mark hint as skipped with reason."""
        self.status = CtfHintStatus.SKIPPED
        self.skip_reason = reason[:256] if len(reason) > 256 else reason

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hint_id": str(self.hint_id),
            "session_id": str(self.session_id) if self.session_id else None,
            "content": self.content,
            "order": self.order,
            "status": self.status.value,
            "skip_reason": self.skip_reason,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class ReferenceHit:
    """
    Retrieved item from CTF knowledge sources.

    Used to guide solution attempts based on prior solutions or patterns.
    """

    ref_id: UUID = field(default_factory=uuid4)
    session_id: Optional[UUID] = None
    source: CtfReferenceSource = CtfReferenceSource.HEURISTIC
    location: str = ""  # Path or identifier; required
    snippet: Optional[str] = None  # Optional excerpt, <=512 chars
    confidence: float = 0.5  # 0.0–1.0
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ref_id": str(self.ref_id),
            "session_id": str(self.session_id) if self.session_id else None,
            "source": self.source.value,
            "location": self.location,
            "snippet": self.snippet,
            "confidence": self.confidence,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class AttemptStep:
    """
    Recorded shell or Python action with its outcome.

    When is_ctf=true, first AttemptStep must have tool_type in {shell, python}.
    """

    step_id: UUID = field(default_factory=uuid4)
    session_id: Optional[UUID] = None
    user_hint_id: Optional[UUID] = None  # Optional link to originating idea
    tool_type: CtfToolType = CtfToolType.OTHER
    action_summary: str = ""  # Required, <=512 chars; high-level command description
    input_payload: str = ""  # Required; sanitized to exclude secrets
    output_excerpt: Optional[str] = None  # Optional; trimmed to safe length
    outcome: CtfAttemptOutcome = CtfAttemptOutcome.NO_DATA
    risk_level: CtfRiskLevel = CtfRiskLevel.LOW  # Default low; user confirmation for medium/high
    next_recommendation: Optional[str] = None  # Optional suggested next move
    created_at: datetime = field(default_factory=datetime.now)

    def mark_success(self, output: str, next_rec: Optional[str] = None) -> None:
        """Mark step as successful with output."""
        self.outcome = CtfAttemptOutcome.SUCCESS
        self.output_excerpt = output[:1024] if len(output) > 1024 else output
        self.next_recommendation = next_rec

    def mark_error(self, error: str, next_rec: Optional[str] = None) -> None:
        """Mark step as error with message."""
        self.outcome = CtfAttemptOutcome.ERROR
        self.output_excerpt = error[:1024] if len(error) > 1024 else error
        self.next_recommendation = next_rec

    def mark_no_data(self, next_rec: Optional[str] = None) -> None:
        """Mark step as no data returned."""
        self.outcome = CtfAttemptOutcome.NO_DATA
        self.next_recommendation = next_rec

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": str(self.step_id),
            "session_id": str(self.session_id) if self.session_id else None,
            "user_hint_id": str(self.user_hint_id) if self.user_hint_id else None,
            "tool_type": self.tool_type.value,
            "action_summary": self.action_summary,
            "input_payload": self.input_payload,
            "output_excerpt": self.output_excerpt,
            "outcome": self.outcome.value,
            "risk_level": self.risk_level.value,
            "next_recommendation": self.next_recommendation,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class CtfSession:
    """
    Main CTF session state.

    State transitions: created → active → paused → active → closed
    No reopening closed sessions.
    """

    session_id: UUID = field(default_factory=uuid4)
    is_ctf: bool = False  # Derived from user intent + heuristics; once true, stays true until close
    challenge_summary: str = ""  # Required when is_ctf=true; concise (<=512 chars)
    status: CtfSessionStatus = CtfSessionStatus.CREATED
    detection_source: CtfDetectionSource = CtfDetectionSource.HEURISTIC
    last_action_at: datetime = field(default_factory=datetime.now)
    non_ctf_guard: bool = False  # If true, suppresses CTF overrides for this session
    created_at: datetime = field(default_factory=datetime.now)

    # Related entities (1-to-many)
    hints: List[UserHint] = field(default_factory=list)
    references: List[ReferenceHit] = field(default_factory=list)
    steps: List[AttemptStep] = field(default_factory=list)

    # Tracking for loop detection
    consecutive_no_data_count: int = 0

    def activate(self) -> None:
        """Transition to active state."""
        if self.status != CtfSessionStatus.CLOSED:
            self.status = CtfSessionStatus.ACTIVE
            self.last_action_at = datetime.now()

    def pause(self) -> None:
        """Transition to paused state (waiting for guidance)."""
        if self.status == CtfSessionStatus.ACTIVE:
            self.status = CtfSessionStatus.PAUSED
            self.last_action_at = datetime.now()

    def close(self) -> None:
        """Close the session (no reopening)."""
        self.status = CtfSessionStatus.CLOSED
        self.last_action_at = datetime.now()

    def add_hint(self, content: str) -> UserHint:
        """Add a user hint to the session."""
        hint = UserHint(
            session_id=self.session_id,
            content=content[:1024] if len(content) > 1024 else content,
            order=len(self.hints),
        )
        self.hints.append(hint)
        return hint

    def add_reference(
        self, source: CtfReferenceSource, location: str, snippet: Optional[str] = None, confidence: float = 0.5
    ) -> ReferenceHit:
        """Add a reference hit to the session."""
        ref = ReferenceHit(
            session_id=self.session_id,
            source=source,
            location=location,
            snippet=snippet[:512] if snippet and len(snippet) > 512 else snippet,
            confidence=confidence,
        )
        self.references.append(ref)
        return ref

    def add_step(
        self,
        tool_type: CtfToolType,
        action_summary: str,
        input_payload: str,
        risk_level: CtfRiskLevel = CtfRiskLevel.LOW,
        user_hint_id: Optional[UUID] = None,
    ) -> AttemptStep:
        """Add an attempt step to the session."""
        step = AttemptStep(
            session_id=self.session_id,
            user_hint_id=user_hint_id,
            tool_type=tool_type,
            action_summary=action_summary[:512] if len(action_summary) > 512 else action_summary,
            input_payload=input_payload,
            risk_level=risk_level,
        )
        self.steps.append(step)
        self.last_action_at = datetime.now()
        return step

    def record_step_outcome(self, step: AttemptStep) -> None:
        """Record step outcome and update loop detection."""
        if step.outcome == CtfAttemptOutcome.NO_DATA:
            self.consecutive_no_data_count += 1
        else:
            self.consecutive_no_data_count = 0

    def should_break_loop(self, threshold: int = 2) -> bool:
        """Check if we should break out of no-data loop."""
        return self.consecutive_no_data_count >= threshold

    def get_pending_hints(self) -> List[UserHint]:
        """Get hints that are still queued."""
        return [h for h in self.hints if h.status == CtfHintStatus.QUEUED]

    def get_hint_contents(self) -> List[str]:
        """Get all hint contents as a list of strings."""
        return [h.content for h in self.hints if h.content]

    def get_last_step(self) -> Optional[AttemptStep]:
        """Get the most recent attempt step."""
        return self.steps[-1] if self.steps else None

    def validate_first_step(self) -> bool:
        """Validate that first step uses shell/python when is_ctf=true."""
        if not self.is_ctf or not self.steps:
            return True
        first_step = self.steps[0]
        return first_step.tool_type in (CtfToolType.SHELL, CtfToolType.PYTHON)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": str(self.session_id),
            "is_ctf": self.is_ctf,
            "challenge_summary": self.challenge_summary,
            "status": self.status.value,
            "detection_source": self.detection_source.value,
            "last_action_at": self.last_action_at.isoformat(),
            "non_ctf_guard": self.non_ctf_guard,
            "created_at": self.created_at.isoformat(),
            "hints": [h.to_dict() for h in self.hints],
            "references": [r.to_dict() for r in self.references],
            "steps": [s.to_dict() for s in self.steps],
            "consecutive_no_data_count": self.consecutive_no_data_count,
        }


class CtfSessionStore:
    """
    In-memory store for CTF sessions (thread-safe).

    Provides accessors and lifecycle helpers for CTF session management.
    Each session is isolated by session_id, ensuring proper session-scope.

    Note:
        This is an application-level singleton that manages session-scoped data.
        Thread-safe for concurrent access.
    """

    def __init__(self):
        self._sessions: Dict[UUID, CtfSession] = {}
        self._lock = Lock()  # Thread-safe access to _sessions dict

    def create_session(
        self,
        is_ctf: bool = False,
        challenge_summary: str = "",
        detection_source: CtfDetectionSource = CtfDetectionSource.HEURISTIC,
        non_ctf_guard: bool = False,
    ) -> CtfSession:
        """Create a new CTF session (thread-safe)."""
        session = CtfSession(
            is_ctf=is_ctf,
            challenge_summary=challenge_summary[:512] if len(challenge_summary) > 512 else challenge_summary,
            detection_source=detection_source,
            non_ctf_guard=non_ctf_guard,
        )
        with self._lock:
            self._sessions[session.session_id] = session
        return session

    def get_session(self, session_id: UUID) -> Optional[CtfSession]:
        """Get a session by ID."""
        return self._sessions.get(session_id)

    def get_or_create_session(self, session_id: UUID, **kwargs) -> CtfSession:
        """Get existing session or create new one (thread-safe)."""
        with self._lock:
            if session_id in self._sessions:
                return self._sessions[session_id]
            session = CtfSession(session_id=session_id, **kwargs)
            self._sessions[session_id] = session
            return session

    def update_session(self, session: CtfSession) -> None:
        """Update a session in the store (thread-safe)."""
        with self._lock:
            self._sessions[session.session_id] = session

    def close_session(self, session_id: UUID) -> Optional[CtfSession]:
        """Close a session and return it."""
        session = self._sessions.get(session_id)
        if session:
            session.close()
        return session

    def delete_session(self, session_id: UUID) -> bool:
        """Delete a session from the store (thread-safe)."""
        with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                return True
            return False

    def list_active_sessions(self) -> List[CtfSession]:
        """List all active CTF sessions."""
        return [s for s in self._sessions.values() if s.status == CtfSessionStatus.ACTIVE and s.is_ctf]

    def cleanup_old_sessions(self, max_age_hours: int = 24) -> int:
        """Remove sessions older than max_age_hours. Returns count removed (thread-safe)."""
        now = datetime.now()
        to_remove = []

        with self._lock:
            for session_id, session in self._sessions.items():
                age = (now - session.created_at).total_seconds() / 3600
                if age > max_age_hours:
                    to_remove.append(session_id)

            for session_id in to_remove:
                del self._sessions[session_id]

        return len(to_remove)


# Application-level singleton for CTF session management
# Note: This is NOT user/session data - it's a thread-safe container that manages
# session-scoped CtfSession objects, properly isolated by session_id.
_ctf_session_store: Optional[CtfSessionStore] = None
_store_lock = Lock()


def get_ctf_session_store() -> CtfSessionStore:
    """
    Get the application-level CTF session store singleton (thread-safe).

    Returns:
        CtfSessionStore instance that manages session-scoped CTF data.

    Note:
        This singleton is justified because:
        1. CtfSessionStore is stateless - it's just a container manager
        2. All actual session data is isolated by session_id
        3. Thread-safe for concurrent access
        4. Similar to dependency injection containers or connection pools
    """
    global _ctf_session_store
    if _ctf_session_store is None:
        with _store_lock:
            # Double-check locking pattern
            if _ctf_session_store is None:
                _ctf_session_store = CtfSessionStore()
    return _ctf_session_store
