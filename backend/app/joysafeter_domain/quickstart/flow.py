"""Canonical quickstart flow vocabulary.

Quickstart has one product state model across domain, application, API, and
frontend: understand -> design -> secure -> prove. UI sub-steps are presentation
details and must never cross the API boundary as numbered steps.
"""

from enum import StrEnum


class QuickstartPhase(StrEnum):
    UNDERSTAND = "understand"
    DESIGN = "design"
    SECURE = "secure"
    PROVE = "prove"


class QuickstartArtifact(StrEnum):
    ENGINE_PLAN = "engine_plan"
    AGENT_BLUEPRINT = "agent_blueprint"
    SECURITY_PLAN = "security_plan"
    EXECUTION_PROOF = "execution_proof"
