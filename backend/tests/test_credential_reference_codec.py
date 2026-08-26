from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.joysafeter_domain.credentials.references import (
    CODEC_SUPPORTED_REFERENCE_PATHS,
    CredentialReferenceCodec,
    SnapshotSchema,
    _validate_reference_path_inventory,
    credential_reference_metric_snapshot,
    reset_credential_reference_metrics,
    snapshot_model_credential_id,
)
from app.joysafeter_shared.ids import CredentialId

CONTRACT = json.loads(
    (Path(__file__).resolve().parents[1] / "contracts" / "credential_reference_contract.json").read_text()
)
CREDENTIAL_A = "cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f010"
CREDENTIAL_B = "cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f011"
BARE_UUID = "018f6f42-0a51-7cc4-98c8-4f6f0ca5f010"
FIXTURE_MATRIX = CONTRACT["fixture_matrix"]
REFERENCE_CASES = [(entry, schema) for entry in CONTRACT["reference_paths"] for schema in entry["schemas"]]


@pytest.mark.no_db
def test_runtime_codec_accepts_only_canonical_v2_snapshot_fields() -> None:
    codec = CredentialReferenceCodec()
    canonical = {
        "schema": "joysafeter.agent_execution_snapshot.v2",
        "engine_kind": "claude",
        "model_credential_id": CREDENTIAL_A,
        "environment_credential_ids": [CREDENTIAL_B],
        "credential_group_ids": [],
        "environment": {
            "config": {
                "environment_credential_ids": [CREDENTIAL_B],
                "egress_services": [
                    {
                        "base_url": "https://crm.example.com",
                        "credential_ref": CREDENTIAL_A,
                        "inject": {"type": "bearer", "credential_field": "TOKEN"},
                    }
                ],
            }
        },
    }

    decoded = codec.decode_snapshot(canonical)
    assert tuple(map(str, decoded.credential_ids)) == (CREDENTIAL_A, CREDENTIAL_B)
    assert snapshot_model_credential_id(canonical) == CredentialId.from_public(CREDENTIAL_A)

    for invalid in (
        {**canonical, "schema": "joysafeter.agent_execution_snapshot.v1"},
        {key: value for key, value in canonical.items() if key != "schema"},
        {**canonical, "secret_ref": CREDENTIAL_A},
        {**canonical, "secret_refs": [CREDENTIAL_B]},
        {**canonical, "vault_ids": []},
    ):
        with pytest.raises(ValueError, match="corrupt_record"):
            codec.decode_snapshot(invalid)


@pytest.mark.no_db
def test_runtime_environment_codec_rejects_all_legacy_aliases() -> None:
    codec = CredentialReferenceCodec()
    canonical = {
        "environment_credential_ids": [CREDENTIAL_A],
        "egress_services": [
            {
                "base_url": "https://crm.example.com",
                "credential_ref": CREDENTIAL_B,
                "inject": {"type": "bearer", "credential_field": "TOKEN"},
            }
        ],
    }
    decoded = codec.decode_environment(canonical)
    assert tuple(map(str, decoded.credential_ids)) == (CREDENTIAL_A, CREDENTIAL_B)

    for invalid in (
        {"secret_refs": [CREDENTIAL_A]},
        {"service_credential_id": CREDENTIAL_A},
        {"egress_services": [{"base_url": "https://crm.example.com", "service_credential_id": CREDENTIAL_A}]},
        {
            "egress_services": [
                {
                    "base_url": "https://crm.example.com",
                    "credential_ref": CREDENTIAL_A,
                    "inject": {"secret_key": "TOKEN"},
                }
            ]
        },
    ):
        with pytest.raises(ValueError, match="corrupt_record"):
            codec.decode_environment(invalid)


@pytest.mark.no_db
def test_runtime_encoders_emit_only_canonical_v2_fields() -> None:
    codec = CredentialReferenceCodec()
    snapshot = codec.encode_snapshot(
        {
            "schema": "joysafeter.agent_execution_snapshot.v2",
            "engine_kind": "claude",
            "model_credential_id": CREDENTIAL_A,
            "environment_credential_ids": [CREDENTIAL_B],
            "environment": {
                "config": {
                    "egress_services": [
                        {
                            "base_url": "https://crm.example.com",
                            "credential_ref": CREDENTIAL_A,
                            "inject": {"credential_field": "TOKEN"},
                        }
                    ]
                }
            },
        }
    )
    assert snapshot["schema"] == "joysafeter.agent_execution_snapshot.v2"
    assert snapshot["environment_credential_ids"] == [CREDENTIAL_B]
    assert snapshot["environment"]["config"]["egress_services"][0]["credential_ref"] == CREDENTIAL_A


@pytest.mark.no_db
def test_contract_and_codec_supported_path_inventories_match_bidirectionally() -> None:
    registered = frozenset((str(entry["document"]), str(entry["path"])) for entry in CONTRACT["reference_paths"])

    assert len(CODEC_SUPPORTED_REFERENCE_PATHS) == 13
    assert registered == CODEC_SUPPORTED_REFERENCE_PATHS


@pytest.mark.no_db
@pytest.mark.parametrize(
    "removed_path",
    sorted(CODEC_SUPPORTED_REFERENCE_PATHS),
    ids=lambda path: f"{path[0]}:{path[1]}",
)
def test_contract_completeness_gate_rejects_removing_any_codec_supported_path(
    removed_path: tuple[str, str],
) -> None:
    mutated_paths = [
        entry for entry in CONTRACT["reference_paths"] if (str(entry["document"]), str(entry["path"])) != removed_path
    ]

    with pytest.raises(ValueError, match="missing Codec-supported paths"):
        _validate_reference_path_inventory(mutated_paths)


@pytest.mark.no_db
def test_contract_declares_shared_fixture_matrix_and_parity_vectors() -> None:
    fixture_matrix = CONTRACT["fixture_matrix"]
    assert fixture_matrix["generator"] == "reference_paths_x_schemas"
    assert fixture_matrix["credential_id"] == CREDENTIAL_A
    assert fixture_matrix["secondary_credential_id"] == CREDENTIAL_B
    assert {vector["category"] for vector in CONTRACT["parity_vectors"]} >= {
        "malformed",
        "duplicates",
        "normalization",
        "unknown_schema",
    }


@pytest.mark.no_db
def test_dependency_scanner_path_allowlists_match_contract() -> None:
    from app.joysafeter_infrastructure.credentials import dependency_scanners

    credential_paths = [entry for entry in CONTRACT["reference_paths"] if entry["value_kind"] == "credential_id"]

    def paths(*, documents: set[str], surfaces: set[str]) -> frozenset[str]:
        return frozenset(
            str(entry["path"])
            for entry in credential_paths
            if entry["document"] in documents and entry["surface"] in surfaces
        )

    snapshot_documents = {"agent_version_snapshot", "active_session_snapshot"}
    assert dependency_scanners._SNAPSHOT_PRIMARY_PATHS == paths(
        documents=snapshot_documents,
        surfaces={"agent_version_executable_snapshot", "active_session_model_environment_snapshot"},
    )
    assert dependency_scanners._ENVIRONMENT_PRIMARY_PATHS == paths(
        documents={"environment_config"},
        surfaces={"live_environment_direct_injection", "live_environment_http_egress_binding"},
    )


def _document_for_case(entry: dict[str, object], schema: str) -> dict[str, object]:
    path = str(entry["path"])
    fixture_value = (
        FIXTURE_MATRIX["credential_field"]
        if entry["value_kind"] == "credential_field"
        else FIXTURE_MATRIX["credential_id"]
    )

    def build(segments: list[str]) -> dict[str, object]:
        segment = segments[0]
        expand = segment.endswith("[*]")
        key = segment[:-3] if expand else segment
        child: object = fixture_value if len(segments) == 1 else build(segments[1:])
        return {key: [child] if expand else child}

    document = build(path.removeprefix("$.").split("."))
    if schema != "live" and CONTRACT["snapshot_schemas"][schema] is not None:
        document["schema"] = CONTRACT["snapshot_schemas"][schema]
    if "model_credential_id" in path:
        document.update({"engine_kind": "claude", "model": {"id": "claude-sonnet"}})
    if "egress_services" in path:
        config = document.get("environment", document)
        if isinstance(config, dict) and "config" in config:
            config = config["config"]
        service = config["egress_services"][0]
        service.update({"name": "crm", "base_url": "https://crm.example.com/api"})
        service.setdefault("credential_ref", FIXTURE_MATRIX["credential_id"])
        inject = service.setdefault("inject", {})
        inject.setdefault("type", FIXTURE_MATRIX["inject_type"])
        inject.setdefault("credential_field", FIXTURE_MATRIX["credential_field"])
    return document


@pytest.mark.no_db
def test_contract_schema_vectors_drive_snapshot_reader() -> None:
    codec = CredentialReferenceCodec()

    for vector in CONTRACT["test_vectors"]:
        document = {} if vector["schema"] is None else {"schema": vector["schema"]}
        if vector["result"] == "corrupt_record":
            with pytest.raises(ValueError, match="corrupt_record"):
                codec.decode_snapshot(document)
        else:
            assert codec.decode_snapshot(document).schema is SnapshotSchema(vector["result"])


@pytest.mark.no_db
@pytest.mark.parametrize(
    ("entry", "schema"),
    REFERENCE_CASES,
    ids=[f"{entry['scanner_fixture']}[{schema}]" for entry, schema in REFERENCE_CASES],
)
def test_every_registered_contract_path_schema_case_is_decoded(
    entry: dict[str, object],
    schema: str,
) -> None:
    codec = CredentialReferenceCodec()
    document = _document_for_case(entry, schema)

    if entry["document"] == "environment_config":
        decoded = codec.decode_environment(document)
    else:
        decoded = codec.decode_snapshot(document)

    if entry["value_kind"] == "credential_id":
        assert CREDENTIAL_A in {str(credential_id) for credential_id in decoded.credential_ids}
    else:
        assert decoded.http_egress[0].credential_field == FIXTURE_MATRIX["credential_field"]


@pytest.mark.no_db
def test_snapshot_mixed_aliases_are_rejected() -> None:
    codec = CredentialReferenceCodec()
    with pytest.raises(ValueError, match="corrupt_record"):
        codec.decode_snapshot(
            {
                "schema": "joysafeter.agent_execution_snapshot.v2",
                "engine_kind": "claude",
                "model": {"id": "claude-sonnet"},
                "model_credential_id": CREDENTIAL_A,
                "secret_ref": CREDENTIAL_A,
            }
        )


@pytest.mark.no_db
@pytest.mark.parametrize(
    "vector",
    CONTRACT["parity_vectors"],
    ids=[vector["name"] for vector in CONTRACT["parity_vectors"]],
)
def test_shared_contract_parity_vectors(vector: dict[str, object]) -> None:
    codec = CredentialReferenceCodec()
    decode = codec.decode_environment if vector["document"] == "environment_config" else codec.decode_snapshot

    if vector["result"] == "corrupt_record":
        with pytest.raises(ValueError, match="corrupt_record"):
            decode(vector["input"])
        return

    decoded = decode(vector["input"])
    if "expected_credential_ids" in vector:
        assert tuple(map(str, decoded.credential_ids)) == tuple(vector["expected_credential_ids"])
    if "expected_inject_types" in vector:
        assert tuple(reference.inject_kind for reference in decoded.http_egress) == tuple(
            vector["expected_inject_types"]
        )


@pytest.mark.no_db
@pytest.mark.parametrize(
    "document",
    [
        {"model_credential_id": CREDENTIAL_A, "secret_ref": CREDENTIAL_B, "engine_kind": "claude"},
        {"model_credential_id": BARE_UUID, "engine_kind": "claude"},
        {"model_credential_id": 7, "engine_kind": "claude"},
        {"model_credential_id": "", "engine_kind": "claude"},
        {"environment_credential_ids": [CREDENTIAL_A, 7]},
        {"environment_credential_ids": BARE_UUID},
        {
            "environment": {
                "config": {
                    "egress_services": [
                        {
                            "base_url": "https://crm.example.com",
                            "service_credential_id": CREDENTIAL_A,
                            "inject": {"credential_field": 7},
                        }
                    ]
                }
            }
        },
        {
            "environment": {
                "config": {
                    "egress_services": [
                        {
                            "base_url": "https://crm.example.com",
                            "service_credential_id": CREDENTIAL_A,
                            "inject": {"credential_field": "A" * 129},
                        }
                    ]
                }
            }
        },
        {
            "environment": {
                "config": {
                    "egress_services": [
                        {
                            "base_url": "https://crm.example.com",
                            "service_credential_id": CREDENTIAL_A,
                            "credential_ref": CREDENTIAL_B,
                            "inject": {"secret_key": "TOKEN"},
                        }
                    ]
                }
            }
        },
    ],
)
def test_snapshot_malformed_or_conflicting_reference_fields_fail_closed(
    document: dict[str, object],
) -> None:
    with pytest.raises((TypeError, ValueError), match="corrupt_record"):
        CredentialReferenceCodec().decode_snapshot(document)


@pytest.mark.no_db
def test_null_and_empty_reference_collections_are_compatible() -> None:
    codec = CredentialReferenceCodec()

    snapshot = codec.decode_snapshot(
        {
            "schema": "joysafeter.agent_execution_snapshot.v2",
            "model_credential_id": None,
            "environment_credential_ids": None,
            "environment": {"config": {"environment_credential_ids": None, "egress_services": None}},
        }
    )
    environment = codec.decode_environment(
        {
            "environment_credential_ids": None,
            "egress_services": None,
        }
    )

    assert snapshot.credential_ids == ()
    assert environment.credential_ids == ()


@pytest.mark.no_db
def test_environment_reader_accepts_canonical_fields_and_deduplicates() -> None:
    decoded = CredentialReferenceCodec().decode_environment(
        {
            "environment_credential_ids": [CREDENTIAL_A, CREDENTIAL_A, CREDENTIAL_B],
            "egress_services": [
                {
                    "name": "crm",
                    "base_url": "https://crm.example.com",
                    "credential_ref": CREDENTIAL_A,
                    "inject": {
                        "type": "raw_header",
                        "credential_field": "TOKEN",
                        "header": "x-token",
                    },
                }
            ],
        }
    )

    assert tuple(map(str, decoded.direct_credential_ids)) == (CREDENTIAL_A, CREDENTIAL_B)
    assert len(decoded.http_egress) == 1
    assert decoded.http_egress[0].credential_field == "TOKEN"
    assert tuple(map(str, decoded.credential_ids)) == (CREDENTIAL_A, CREDENTIAL_B)


@pytest.mark.no_db
def test_encoders_emit_only_canonical_persistent_keys() -> None:
    codec = CredentialReferenceCodec()
    snapshot = codec.encode_snapshot(
        {
            "engine_kind": "claude",
            "model_credential_id": CREDENTIAL_A,
            "environment_credential_ids": [CREDENTIAL_B],
            "environment": {
                "config": {
                    "environment_credential_ids": [CREDENTIAL_B],
                    "egress_services": [
                        {
                            "base_url": "https://crm.example.com",
                            "credential_ref": CREDENTIAL_A,
                            "inject": {"credential_field": "TOKEN"},
                        }
                    ],
                }
            },
        }
    )
    environment = codec.encode_environment(
        {
            "environment_credential_ids": [CREDENTIAL_A],
            "egress_services": [
                {
                    "base_url": "https://crm.example.com",
                    "credential_ref": CREDENTIAL_B,
                    "inject": {"credential_field": "TOKEN"},
                }
            ],
        }
    )

    assert snapshot["schema"] == CONTRACT["snapshot_schemas"]["v2"]
    assert snapshot["environment_credential_ids"] == [CREDENTIAL_B]
    assert snapshot["environment"]["config"]["environment_credential_ids"] == [CREDENTIAL_B]
    assert snapshot["environment"]["config"]["egress_services"][0]["credential_ref"] == CREDENTIAL_A
    assert snapshot["environment"]["config"]["egress_services"][0]["inject"] == {"credential_field": "TOKEN"}
    assert environment["environment_credential_ids"] == [CREDENTIAL_A]
    assert environment["egress_services"][0]["credential_ref"] == CREDENTIAL_B
    assert environment["egress_services"][0]["inject"] == {"credential_field": "TOKEN"}


@pytest.mark.no_db
def test_reference_metrics_expose_only_normalized_versions_keys_and_counts() -> None:
    reset_credential_reference_metrics()
    codec = CredentialReferenceCodec()
    codec.decode_snapshot(
        {
            "schema": CONTRACT["snapshot_schemas"]["v2"],
            "engine_kind": "claude",
            "model_credential_id": CREDENTIAL_A,
        }
    )
    codec.encode_environment({"environment_credential_ids": [CREDENTIAL_B]})
    unknown = "joysafeter.agent_execution_snapshot.private-customer-value"
    with pytest.raises(ValueError, match="corrupt_record"):
        codec.decode_snapshot({"schema": unknown})

    metrics = credential_reference_metric_snapshot()
    rendered = repr(metrics)

    assert metrics.reader_versions[("snapshot", "v2", "success")] == 1
    assert metrics.reader_versions[("snapshot", "unknown", "error")] == 1
    assert (
        metrics.persisted_keys[("environment", "live", "$.environment_credential_ids[*]", "environment_credential_ids")]
        == 1
    )
    assert CREDENTIAL_A not in rendered
    assert CREDENTIAL_B not in rendered
    assert unknown not in rendered


@pytest.mark.no_db
def test_persisted_key_metrics_ignore_registered_names_outside_contract_paths() -> None:
    reset_credential_reference_metrics()
    codec = CredentialReferenceCodec()

    codec.encode_environment(
        {
            "metadata": {
                "credential_ref": CREDENTIAL_A,
                "secret_key": "not-a-reference-field",
            }
        }
    )

    metrics = credential_reference_metric_snapshot()
    assert dict(metrics.persisted_keys) == {}
