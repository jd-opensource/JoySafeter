"""Read-only P0.5 credential-domain preflight inventory."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

# Direct execution initializes the backend import path and safe defaults before
# loading application modules.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
os.environ.setdefault("SECRET_KEY", "credential-p0-5-preflight-read-only")

from jsonschema import Draft202012Validator  # noqa: E402
from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.joysafeter_domain.models.joysafeter_agent import (  # noqa: E402
    JoySafeterAgent,
    JoySafeterAgentVersion,
)
from app.joysafeter_domain.models.joysafeter_credential import JoySafeterCredential  # noqa: E402
from app.joysafeter_domain.models.joysafeter_environment import JoySafeterEnvironment  # noqa: E402
from app.joysafeter_domain.models.joysafeter_session import (  # noqa: E402
    JoySafeterSession,
    SessionStatus,
)
from app.joysafeter_domain.models.joysafeter_trigger import JoySafeterTrigger  # noqa: E402
from app.joysafeter_shared.database import async_session_factory, engine  # noqa: E402

_SCHEMA_PATH = BACKEND_ROOT / "contracts" / "credential_p0_5_preflight.schema.json"
_SNAPSHOT_SCHEMA_COUNTS = ("legacy-v0", "v1", "v2", "unknown")
_REFERENCE_KEYS = frozenset(
    {
        "model_credential_id",
        "environment_credential_ids",
        "secret_ref",
        "secret_refs",
        "service_credential_id",
        "webhook_auth_credential_id",
    }
)
_LEGACY_REFERENCE_KEYS = frozenset({"secret_ref", "secret_refs", "service_credential_id", "secret_key"})


@dataclass(frozen=True)
class CredentialPreflightReport:
    invalid_resources: tuple[dict[str, str], ...]
    credential_type_counts: Mapping[str, int]
    snapshot_schema_counts: Mapping[str, int]
    legacy_reference_counts: Mapping[str, int]
    cross_project_references: tuple[dict[str, str], ...]
    null_project_references: tuple[dict[str, str], ...]
    mcp_url_conflicts: tuple[dict[str, str], ...]


def _normalized_field_path(parts: tuple[str | int, ...]) -> str:
    result = ""
    for part in parts:
        if isinstance(part, int):
            result += f"[{part}]"
        elif result:
            result += f".{part}"
        else:
            result = part
    return result


def _count_path(parts: tuple[str | int, ...]) -> str:
    return _normalized_field_path(tuple("[]" if isinstance(part, int) else part for part in parts)).replace(".[]", "[]")


def _snapshot_schema(snapshot: object) -> str:
    if not isinstance(snapshot, dict):
        return "unknown"
    schema = snapshot.get("schema")
    if schema is None:
        return "legacy-v0"
    if schema == "joysafeter.agent_execution_snapshot.v1":
        return "v1"
    if schema == "joysafeter.agent_execution_snapshot.v2":
        return "v2"
    return "unknown"


def _iter_references(value: object, path: tuple[str | int, ...] = ()) -> Iterable[tuple[str, str, bool]]:
    if isinstance(value, dict):
        for key, nested_value in value.items():
            nested_path = (*path, str(key))
            if key in _REFERENCE_KEYS:
                if key in {"environment_credential_ids", "secret_refs"} and isinstance(nested_value, list):
                    for index, reference in enumerate(nested_value):
                        if isinstance(reference, str) and reference:
                            yield (
                                _normalized_field_path((*nested_path, index)),
                                reference,
                                key in _LEGACY_REFERENCE_KEYS,
                            )
                elif isinstance(nested_value, str) and nested_value:
                    yield _normalized_field_path(nested_path), nested_value, key in _LEGACY_REFERENCE_KEYS
            yield from _iter_references(nested_value, nested_path)
    elif isinstance(value, list):
        for index, nested_value in enumerate(value):
            yield from _iter_references(nested_value, (*path, index))


def _iter_legacy_paths(value: object, path: tuple[str | int, ...] = ()) -> Iterable[str]:
    if isinstance(value, dict):
        for key, nested_value in value.items():
            nested_path = (*path, str(key))
            if key in _LEGACY_REFERENCE_KEYS:
                if key == "secret_refs" and isinstance(nested_value, list):
                    for index, _ in enumerate(nested_value):
                        yield _count_path((*nested_path, index))
                else:
                    yield _count_path(nested_path)
            yield from _iter_legacy_paths(nested_value, nested_path)
    elif isinstance(value, list):
        for index, nested_value in enumerate(value):
            yield from _iter_legacy_paths(nested_value, (*path, index))


def _invalid_resource_entries(credential: JoySafeterCredential) -> Iterable[dict[str, str]]:
    common = {
        "error_class": "INVALID_KIND_IDENTITY",
        "field_path": "kind_identity",
        "resource_id": str(credential.id),
        "surface": "credential",
    }
    if credential.kind == "model":
        valid = (
            credential.provider is not None
            and credential.protocol is not None
            and credential.mcp_server_url is None
            and credential.normalized_mcp_server_url is None
            and credential.credential_type is None
            and credential.oauth_config is None
            and credential.group_id is None
        )
    elif credential.kind == "mcp":
        valid = (
            credential.mcp_server_url is not None
            and credential.normalized_mcp_server_url is not None
            and credential.credential_type is not None
            and credential.group_id is not None
            and credential.provider is None
            and credential.protocol is None
            and not credential.is_default
        )
    elif credential.kind == "service":
        valid = (
            credential.provider is None
            and credential.protocol is None
            and credential.mcp_server_url is None
            and credential.normalized_mcp_server_url is None
            and credential.credential_type is None
            and credential.oauth_config is None
            and credential.group_id is None
            and not credential.is_default
        )
    else:
        valid = False
    if not valid:
        yield common


def _reference_entry(
    *,
    error_class: str,
    surface: str,
    field_path: str,
    resource_id: str,
) -> dict[str, str]:
    return {
        "error_class": error_class,
        "field_path": field_path,
        "resource_id": resource_id,
        "surface": surface,
    }


def _inspect_references(
    *,
    owner_project_id: str | None,
    surface: str,
    value: object,
    credential_projects: Mapping[str, str],
    legacy_reference_counts: Counter[str],
    cross_project_references: list[dict[str, str]],
    null_project_references: list[dict[str, str]],
    field_path_prefix: str = "",
    legacy_count_surface: str | None = None,
) -> None:
    for path in _iter_legacy_paths(value):
        legacy_reference_counts[f"{legacy_count_surface or surface}.{path}"] += 1
    for field_path, credential_id, _ in _iter_references(value):
        report_field_path = f"{field_path_prefix}.{field_path}" if field_path_prefix else field_path
        if owner_project_id is None:
            null_project_references.append(
                _reference_entry(
                    error_class="NULL_PROJECT_CREDENTIAL_REFERENCE",
                    surface=surface,
                    field_path=report_field_path,
                    resource_id=credential_id,
                )
            )
        elif credential_projects.get(credential_id) not in (None, owner_project_id):
            cross_project_references.append(
                _reference_entry(
                    error_class="CROSS_PROJECT_CREDENTIAL_REFERENCE",
                    surface=surface,
                    field_path=report_field_path,
                    resource_id=credential_id,
                )
            )


async def collect_credential_preflight(db_session: AsyncSession) -> CredentialPreflightReport:
    credentials = list(
        (await db_session.execute(select(JoySafeterCredential).order_by(JoySafeterCredential.id))).scalars()
    )
    credential_projects = {str(credential.id): credential.project_id for credential in credentials}
    credential_type_counts = Counter(
        credential.credential_type for credential in credentials if credential.credential_type is not None
    )
    invalid_resources = [entry for credential in credentials for entry in _invalid_resource_entries(credential)]
    legacy_reference_counts: Counter[str] = Counter()
    cross_project_references: list[dict[str, str]] = []
    null_project_references: list[dict[str, str]] = []
    snapshot_schema_counts: Counter[str] = Counter({key: 0 for key in _SNAPSHOT_SCHEMA_COUNTS})

    agents = list((await db_session.execute(select(JoySafeterAgent).order_by(JoySafeterAgent.id))).scalars())
    for agent in agents:
        if agent.model_credential_id is None:
            continue
        _inspect_references(
            owner_project_id=agent.project_id,
            surface="agent",
            value={"model_credential_id": str(agent.model_credential_id)},
            credential_projects=credential_projects,
            legacy_reference_counts=legacy_reference_counts,
            cross_project_references=cross_project_references,
            null_project_references=null_project_references,
        )

    agent_versions = await db_session.execute(
        select(JoySafeterAgentVersion.id, JoySafeterAgent.project_id, JoySafeterAgentVersion.snapshot)
        .join(JoySafeterAgent, JoySafeterAgent.id == JoySafeterAgentVersion.agent_id)
        .order_by(JoySafeterAgentVersion.id)
    )
    for _, project_id, snapshot in agent_versions:
        snapshot_schema_counts[_snapshot_schema(snapshot)] += 1
        _inspect_references(
            owner_project_id=project_id,
            surface="agent_version_snapshot",
            value=snapshot,
            credential_projects=credential_projects,
            legacy_reference_counts=legacy_reference_counts,
            cross_project_references=cross_project_references,
            null_project_references=null_project_references,
            legacy_count_surface="agent_version",
        )

    sessions = await db_session.execute(
        select(JoySafeterSession.id, JoySafeterSession.project_id, JoySafeterSession.agent_snapshot)
        .where(
            JoySafeterSession.agent_snapshot.is_not(None),
            JoySafeterSession.status != SessionStatus.TERMINATED.value,
        )
        .order_by(JoySafeterSession.id)
    )
    for session_id, project_id, snapshot in sessions:
        snapshot_schema = _snapshot_schema(snapshot)
        snapshot_schema_counts[snapshot_schema] += 1
        if snapshot_schema == "unknown":
            invalid_resources.append(
                _reference_entry(
                    error_class="UNKNOWN_ACTIVE_SESSION_SNAPSHOT_SCHEMA",
                    surface="session_snapshot",
                    field_path="schema",
                    resource_id=str(session_id),
                )
            )
        _inspect_references(
            owner_project_id=project_id,
            surface="session_snapshot",
            value=snapshot,
            credential_projects=credential_projects,
            legacy_reference_counts=legacy_reference_counts,
            cross_project_references=cross_project_references,
            null_project_references=null_project_references,
        )

    environments = await db_session.execute(
        select(JoySafeterEnvironment.id, JoySafeterEnvironment.project_id, JoySafeterEnvironment.config).order_by(
            JoySafeterEnvironment.id
        )
    )
    for _, project_id, config in environments:
        _inspect_references(
            owner_project_id=project_id,
            surface="environment",
            value=config,
            credential_projects=credential_projects,
            legacy_reference_counts=legacy_reference_counts,
            cross_project_references=cross_project_references,
            null_project_references=null_project_references,
            field_path_prefix="config",
        )

    triggers = list((await db_session.execute(select(JoySafeterTrigger).order_by(JoySafeterTrigger.id))).scalars())
    for trigger in triggers:
        if trigger.webhook_auth_credential_id is None:
            continue
        _inspect_references(
            owner_project_id=trigger.project_id,
            surface="trigger",
            value={"webhook_auth_credential_id": str(trigger.webhook_auth_credential_id)},
            credential_projects=credential_projects,
            legacy_reference_counts=legacy_reference_counts,
            cross_project_references=cross_project_references,
            null_project_references=null_project_references,
        )

    grouped_urls: dict[tuple[str, str], set[str]] = defaultdict(set)
    for credential in credentials:
        if credential.kind == "mcp" and credential.normalized_mcp_server_url and credential.group_id:
            grouped_urls[(credential.project_id, credential.normalized_mcp_server_url)].add(str(credential.group_id))
    mcp_url_conflicts = [
        _reference_entry(
            error_class="MCP_NORMALIZED_URL_CONFLICT",
            surface="credential_group",
            field_path="normalized_mcp_server_url",
            resource_id=group_id,
        )
        for (_, _), group_ids in sorted(grouped_urls.items())
        if len(group_ids) > 1
        for group_id in sorted(group_ids)
    ]

    return CredentialPreflightReport(
        invalid_resources=tuple(sorted(invalid_resources, key=_entry_sort_key)),
        credential_type_counts=dict(sorted(credential_type_counts.items())),
        snapshot_schema_counts={key: snapshot_schema_counts[key] for key in _SNAPSHOT_SCHEMA_COUNTS},
        legacy_reference_counts=dict(sorted(legacy_reference_counts.items())),
        cross_project_references=tuple(sorted(cross_project_references, key=_entry_sort_key)),
        null_project_references=tuple(sorted(null_project_references, key=_entry_sort_key)),
        mcp_url_conflicts=tuple(sorted(mcp_url_conflicts, key=_entry_sort_key)),
    )


def _entry_sort_key(entry: Mapping[str, str]) -> tuple[str, str, str, str]:
    return (entry["surface"], entry["field_path"], entry["resource_id"], entry["error_class"])


def report_payload(report: CredentialPreflightReport) -> dict[str, object]:
    payload = asdict(report)
    return {
        key: list(payload[key]) if isinstance(payload[key], tuple) else payload[key]
        for key in (
            "credential_type_counts",
            "cross_project_references",
            "invalid_resources",
            "legacy_reference_counts",
            "mcp_url_conflicts",
            "null_project_references",
            "snapshot_schema_counts",
        )
    }


def validate_report(payload: Mapping[str, object]) -> None:
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(dict(payload))


def serialize_report(report: CredentialPreflightReport) -> str:
    payload = report_payload(report)
    validate_report(payload)
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _has_blockers(report: CredentialPreflightReport) -> bool:
    return bool(report.invalid_resources or report.cross_project_references or report.mcp_url_conflicts)


def _blocker_error_classes(report: CredentialPreflightReport) -> tuple[str, ...]:
    error_classes = {entry["error_class"] for entry in report.invalid_resources}
    error_classes.update(entry["error_class"] for entry in report.cross_project_references)
    error_classes.update(entry["error_class"] for entry in report.mcp_url_conflicts)
    return tuple(sorted(error_classes))


async def _run(output_path: Path, fail_on_blocker: bool) -> int:
    async with async_session_factory() as db_session:
        async with db_session.begin():
            await db_session.execute(text("SET TRANSACTION READ ONLY"))
            report = await collect_credential_preflight(db_session)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(serialize_report(report), encoding="utf-8")
    if fail_on_blocker and _has_blockers(report):
        print(
            "credential preflight blockers detected: " + ", ".join(_blocker_error_classes(report)),
            file=sys.stderr,
        )
        return 1
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fail-on-blocker", action="store_true")
    return parser.parse_args()


async def _main(output_path: Path, fail_on_blocker: bool) -> int:
    try:
        return await _run(output_path, fail_on_blocker)
    finally:
        await engine.dispose()


def main() -> int:
    args = _parse_args()
    return asyncio.run(_main(args.output, args.fail_on_blocker))


if __name__ == "__main__":
    raise SystemExit(main())
