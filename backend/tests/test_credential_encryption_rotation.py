from __future__ import annotations

import asyncio
import json
import uuid
from collections import Counter
from dataclasses import asdict
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.joysafeter_application.sensitive_material_cleanup import (
    rewrap_sensitive_material,
    verify_sensitive_material_integrity,
)
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_auth import AuthUser
from app.joysafeter_domain.models.joysafeter_credential import (
    JoySafeterCredential,
    JoySafeterCredentialGroup,
)
from app.joysafeter_domain.models.joysafeter_credential_encryption_canary import (
    JoySafeterCredentialEncryptionCanary,
)
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_domain.models.joysafeter_session_repo import JoySafeterSessionRepo
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask
from app.joysafeter_domain.models.joysafeter_task_identity import JoySafeterTaskIdentityContext
from app.joysafeter_infrastructure.sensitive_material import (
    VersionedMaterialProtector,
    inspect_sensitive_material_envelopes,
    validate_credential_encryption_storage_coverage,
)
from app.joysafeter_shared.security.credential_cipher import (
    CredentialCipher,
    CredentialCipherConfigurationError,
    CredentialCiphertextError,
)
from app.joysafeter_shared.security.credential_encryption_canary import (
    initialize_missing_credential_encryption_canaries,
    validate_credential_encryption_canaries,
)
from app.joysafeter_shared.utils.datetime import utc_now

LEGACY_KEY = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
ACTIVE_KEY = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="
PREVIOUS_KEY = "ICEiIyQlJicoKSorLC0uLzAxMjM0NTY3ODk6Ozw9Pj8="
KEYRING = json.dumps({"active-2026-08": ACTIVE_KEY, "previous-2026-07": PREVIOUS_KEY})


def _rotation_cipher() -> CredentialCipher:
    return CredentialCipher(
        LEGACY_KEY,
        keyring_json=KEYRING,
        write_key_id="active-2026-08",
    )


def _damage_ciphertext(ciphertext: str) -> str:
    prefix, payload = ciphertext.rsplit(":", 1)
    replacement = "A" if payload[0] != "A" else "B"
    return f"{prefix}:{replacement}{payload[1:]}"


async def _wait_until_postgres_backend_is_lock_blocked(db: AsyncSession, backend_pid: int) -> None:
    for _ in range(100):
        wait_event_type = await db.scalar(
            text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"),
            {"pid": backend_pid},
        )
        if wait_event_type == "Lock":
            return
        await asyncio.sleep(0.01)
    pytest.fail("concurrent initializer did not reach the unique-key conflict")


async def _create_project(db_session) -> Project:
    organization = Organization(name=f"crypto-org-{uuid.uuid4()}", slug=f"crypto-org-{uuid.uuid4()}")
    db_session.add(organization)
    await db_session.flush()
    project = Project(org_id=organization.id, name="Crypto Project", slug=f"crypto-{uuid.uuid4()}")
    db_session.add(project)
    await db_session.flush()
    return project


@pytest.mark.asyncio
async def test_canaries_are_explicitly_initialized_and_detect_wrong_key(db_session):
    cipher = _rotation_cipher()

    with pytest.raises(CredentialCipherConfigurationError, match="canary is missing"):
        await validate_credential_encryption_canaries(db_session, cipher)

    assert await initialize_missing_credential_encryption_canaries(db_session, cipher) == (
        "active-2026-08",
        "previous-2026-07",
    )
    await db_session.commit()
    assert await initialize_missing_credential_encryption_canaries(db_session, cipher) == ()
    await validate_credential_encryption_canaries(db_session, cipher)

    wrong_cipher = CredentialCipher(
        LEGACY_KEY,
        keyring_json=json.dumps(
            {
                "active-2026-08": CredentialCipher.generate_key(),
                "previous-2026-07": PREVIOUS_KEY,
            }
        ),
        write_key_id="active-2026-08",
    )
    with pytest.raises(CredentialCipherConfigurationError, match="cannot be decrypted"):
        await validate_credential_encryption_canaries(db_session, wrong_cipher)


@pytest.mark.asyncio
async def test_concurrent_canary_initializers_converge_without_overwriting(postgres_url: str) -> None:
    cipher = CredentialCipher(
        keyring_json=json.dumps({"concurrent-2026-08": ACTIVE_KEY}),
        write_key_id="concurrent-2026-08",
    )
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as winner_db, factory() as loser_db, factory() as observer_db:
            assert await initialize_missing_credential_encryption_canaries(winner_db, cipher) == ("concurrent-2026-08",)
            winner_encrypted_canary = str(
                await winner_db.scalar(
                    text(
                        "SELECT encrypted_canary "
                        "FROM joysafeter_credential_encryption_canaries "
                        "WHERE key_id = 'concurrent-2026-08'"
                    )
                )
            )
            loser_pid = int(await loser_db.scalar(text("SELECT pg_backend_pid()")))
            loser_task = asyncio.create_task(initialize_missing_credential_encryption_canaries(loser_db, cipher))

            await _wait_until_postgres_backend_is_lock_blocked(observer_db, loser_pid)

            await winner_db.commit()
            assert await asyncio.wait_for(loser_task, timeout=2) == ()
            await loser_db.commit()

            persisted = await observer_db.execute(
                text(
                    "SELECT key_id, encrypted_canary "
                    "FROM joysafeter_credential_encryption_canaries "
                    "WHERE key_id = 'concurrent-2026-08'"
                )
            )
            row = persisted.mappings().one()
            assert row["key_id"] == "concurrent-2026-08"
            assert row["encrypted_canary"] == winner_encrypted_canary
            assert cipher.decrypt_stored(str(row["encrypted_canary"])) == (
                "joysafeter-credential-encryption-canary:concurrent-2026-08"
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_canary_validation_failure_rolls_back_partial_initialization(postgres_url: str) -> None:
    winner_cipher = CredentialCipher(
        keyring_json=json.dumps({"z-conflict": ACTIVE_KEY}),
        write_key_id="z-conflict",
    )
    initializer_cipher = CredentialCipher(
        keyring_json=json.dumps({"a-new": ACTIVE_KEY, "z-conflict": PREVIOUS_KEY}),
        write_key_id="a-new",
    )
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as winner_db, factory() as initializer_db, factory() as observer_db:
            assert await initialize_missing_credential_encryption_canaries(winner_db, winner_cipher) == ("z-conflict",)
            winner_encrypted_canary = str(
                await winner_db.scalar(
                    text(
                        "SELECT encrypted_canary "
                        "FROM joysafeter_credential_encryption_canaries "
                        "WHERE key_id = 'z-conflict'"
                    )
                )
            )
            initializer_pid = int(await initializer_db.scalar(text("SELECT pg_backend_pid()")))
            initializer_task = asyncio.create_task(
                initialize_missing_credential_encryption_canaries(initializer_db, initializer_cipher)
            )

            await _wait_until_postgres_backend_is_lock_blocked(observer_db, initializer_pid)
            await winner_db.commit()

            with pytest.raises(CredentialCipherConfigurationError, match="cannot be decrypted"):
                await asyncio.wait_for(initializer_task, timeout=2)
            await initializer_db.commit()

            persisted = (
                (
                    await observer_db.execute(
                        text(
                            "SELECT key_id, encrypted_canary "
                            "FROM joysafeter_credential_encryption_canaries "
                            "ORDER BY key_id"
                        )
                    )
                )
                .mappings()
                .all()
            )
            assert [dict(row) for row in persisted] == [
                {"key_id": "z-conflict", "encrypted_canary": winner_encrypted_canary}
            ]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("key_id", "encrypted_canary"),
    [
        ("bad:key", "enc:v2:bad:key:AA=="),
        ("a_b", "enc:v2:axb:AA=="),
        ("active-2026-08", "enc:v2:active-2026-08:"),
    ],
)
async def test_canary_table_enforces_key_id_and_exact_nonempty_envelope_prefix(
    db_session,
    key_id: str,
    encrypted_canary: str,
):
    db_session.add(
        JoySafeterCredentialEncryptionCanary(
            key_id=key_id,
            encrypted_canary=encrypted_canary,
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_storage_coverage_rejects_removing_legacy_key_while_v1_material_remains(db_session):
    project = await _create_project(db_session)
    legacy = CredentialCipher(LEGACY_KEY)
    db_session.add(
        JoySafeterCredential(
            project_id=project.id,
            kind="service",
            name="legacy-reader-required",
            data={"TOKEN": legacy.encrypt("still-needs-legacy-key")},
        )
    )
    await db_session.commit()
    keyring_only = CredentialCipher(
        keyring_json=json.dumps({"active-2026-08": ACTIVE_KEY}),
        write_key_id="active-2026-08",
    )

    with pytest.raises(CredentialCipherConfigurationError, match="JOYSAFETER_VAULT_ENCRYPTION_KEY.*enc:v1"):
        await validate_credential_encryption_storage_coverage(db_session, keyring_only)


@pytest.mark.asyncio
async def test_storage_coverage_rejects_removing_referenced_v2_key(db_session):
    project = await _create_project(db_session)
    previous_writer = CredentialCipher(
        keyring_json=json.dumps({"previous-2026-07": PREVIOUS_KEY}),
        write_key_id="previous-2026-07",
    )
    db_session.add(
        JoySafeterCredential(
            project_id=project.id,
            kind="service",
            name="previous-reader-required",
            data={"TOKEN": previous_writer.encrypt("still-needs-previous-key")},
        )
    )
    await db_session.commit()
    active_only = CredentialCipher(
        keyring_json=json.dumps({"active-2026-08": ACTIVE_KEY}),
        write_key_id="active-2026-08",
    )

    with pytest.raises(CredentialCipherConfigurationError, match="previous-2026-07"):
        await validate_credential_encryption_storage_coverage(db_session, active_only)


@pytest.mark.asyncio
async def test_storage_coverage_rejects_plaintext_or_unsupported_envelopes(db_session):
    project = await _create_project(db_session)
    db_session.add(
        JoySafeterCredential(
            project_id=project.id,
            kind="service",
            name="invalid-envelope",
            data={"TOKEN": "enc:v3:not-supported"},
        )
    )
    await db_session.commit()

    with pytest.raises(CredentialCipherConfigurationError, match="invalid or plaintext"):
        await validate_credential_encryption_storage_coverage(db_session, _rotation_cipher())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("column_name", "expected_location"),
    [
        ("data", "managed_credential.data=1"),
        ("oauth_config", "managed_credential.oauth_config=1"),
    ],
)
async def test_non_object_credential_json_fails_closed_without_rewrite(
    db_session,
    column_name: str,
    expected_location: str,
) -> None:
    project = await _create_project(db_session)
    if column_name == "data":
        credential = JoySafeterCredential(
            project_id=project.id,
            kind="service",
            name="invalid-data-shape",
            data={"TOKEN": _rotation_cipher().encrypt("valid-before-corruption")},
        )
    else:
        group = JoySafeterCredentialGroup(project_id=project.id, name="invalid-oauth-shape")
        db_session.add(group)
        await db_session.flush()
        credential = JoySafeterCredential(
            project_id=project.id,
            kind="mcp",
            name="invalid-oauth-shape",
            data={},
            mcp_server_url="https://mcp.example.com",
            normalized_mcp_server_url="https://mcp.example.com/",
            credential_type="oauth",
            oauth_config={"client_secret": _rotation_cipher().encrypt("valid-before-corruption")},
            group_id=group.id,
        )
    db_session.add(credential)
    await db_session.flush()
    await db_session.execute(
        text(f"UPDATE joysafeter_credentials SET {column_name} = '[]'::jsonb WHERE id = :id"),
        {"id": credential.id.uuid},
    )
    await db_session.commit()
    db_session.expire_all()

    with pytest.raises(CredentialCipherConfigurationError, match=expected_location):
        await validate_credential_encryption_storage_coverage(db_session, _rotation_cipher())

    protector = VersionedMaterialProtector(
        LEGACY_KEY,
        keyring_json=KEYRING,
        write_key_id="active-2026-08",
    )
    with pytest.raises(CredentialCiphertextError, match=expected_location.removesuffix("=1")):
        await rewrap_sensitive_material(db_session, protector, limit_per_store=1)
    await db_session.commit()

    assert (
        await db_session.scalar(
            text(f"SELECT jsonb_typeof({column_name}) FROM joysafeter_credentials WHERE id = :id"),
            {"id": credential.id.uuid},
        )
        == "array"
    )


@pytest.mark.asyncio
async def test_storage_coverage_requires_an_enabled_cipher_even_when_storage_is_empty(db_session):
    with pytest.raises(CredentialCipherConfigurationError, match="JOYSAFETER_VAULT_ENCRYPTION_KEY"):
        await validate_credential_encryption_storage_coverage(db_session, CredentialCipher())


@pytest.mark.asyncio
async def test_rewrap_is_bounded_across_all_sensitive_material_stores(db_session):
    legacy = CredentialCipher(LEGACY_KEY)
    protector = VersionedMaterialProtector(
        LEGACY_KEY,
        keyring_json=KEYRING,
        write_key_id="active-2026-08",
    )
    organization = Organization(name=f"rotation-org-{uuid.uuid4()}", slug=f"rotation-org-{uuid.uuid4()}")
    user = AuthUser(name="Rotation User", email=f"rotation-{uuid.uuid4()}@example.com")
    agent = JoySafeterAgent(name=f"rotation-agent-{uuid.uuid4()}")
    db_session.add_all([organization, user, agent])
    await db_session.flush()
    project = Project(org_id=organization.id, name="Rotation Project", slug=f"rotation-{uuid.uuid4()}")
    db_session.add(project)
    await db_session.flush()

    credential = JoySafeterCredential(
        project_id=project.id,
        kind="service",
        name="rotation-service",
        data={"TOKEN": legacy.encrypt("managed-secret")},
    )
    session = JoySafeterSession(agent_id=agent.id, status="idle")
    task = JoySafeterTask(agent_id=agent.id, prompt="rotation", status="pending", user_id=user.id)
    db_session.add_all([credential, session, task])
    await db_session.flush()
    now = utc_now()
    repository = JoySafeterSessionRepo(
        session_id=session.id,
        url="https://github.com/example/private.git",
        branch="main",
        mount_path="/workspace/private",
        mount_name="private",
        encrypted_token=legacy.encrypt("repository-secret"),
        token_expires_at=now + timedelta(minutes=10),
        token_rotated_at=now,
    )
    identity = JoySafeterTaskIdentityContext(
        task_id=task.id,
        project_id=project.id,
        user_id=str(user.id),
        credential_kind="identity_token",
        encrypted_credential=legacy.encrypt("identity-secret"),
        captured_at=now,
        expires_at=now + timedelta(minutes=10),
    )
    db_session.add_all([repository, identity])
    await db_session.commit()

    before = await inspect_sensitive_material_envelopes(db_session)
    assert {(entry.surface, entry.envelope, entry.count) for entry in before} == {
        ("managed_credential.data", "enc:v1", 1),
        ("repository_token", "enc:v1", 1),
        ("task_identity", "enc:v1", 1),
    }

    result = await rewrap_sensitive_material(db_session, protector, limit_per_store=1)
    await db_session.commit()

    assert result.managed_credentials == 1
    assert result.task_identities == 1
    assert result.repository_tokens == 1

    await db_session.refresh(credential)
    await db_session.refresh(identity)
    await db_session.refresh(repository)
    assert credential.data["TOKEN"].startswith("enc:v2:active-2026-08:")
    assert identity.encrypted_credential is not None
    assert identity.encrypted_credential.startswith("enc:v2:active-2026-08:")
    assert repository.encrypted_token.startswith("enc:v2:active-2026-08:")
    assert protector.reveal(credential.data["TOKEN"]) == "managed-secret"
    assert protector.reveal(identity.encrypted_credential) == "identity-secret"
    assert protector.reveal(repository.encrypted_token) == "repository-secret"

    after = await inspect_sensitive_material_envelopes(db_session)
    assert {(entry.surface, entry.envelope, entry.count) for entry in after} == {
        ("managed_credential.data", "enc:v2:active-2026-08", 1),
        ("repository_token", "enc:v2:active-2026-08", 1),
        ("task_identity", "enc:v2:active-2026-08", 1),
    }

    assert await rewrap_sensitive_material(db_session, protector, limit_per_store=1) == result.empty()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("surface", "expected_location"),
    [
        ("managed_credential", "managed_credential.data"),
        ("managed_oauth", "managed_credential.oauth_config"),
        ("task_identity", "task_identity"),
        ("repository_token", "repository_token"),
    ],
)
async def test_rewrap_rejects_plaintext_without_silently_encrypting(
    db_session,
    surface: str,
    expected_location: str,
):
    protector = VersionedMaterialProtector(
        LEGACY_KEY,
        keyring_json=KEYRING,
        write_key_id="active-2026-08",
    )
    organization = Organization(name=f"invalid-org-{uuid.uuid4()}", slug=f"invalid-org-{uuid.uuid4()}")
    user = AuthUser(name="Invalid Material User", email=f"invalid-{uuid.uuid4()}@example.com")
    agent = JoySafeterAgent(name=f"invalid-agent-{uuid.uuid4()}")
    db_session.add_all([organization, user, agent])
    await db_session.flush()
    project = Project(org_id=organization.id, name="Invalid Material Project", slug=f"invalid-{uuid.uuid4()}")
    session = JoySafeterSession(agent_id=agent.id, status="idle")
    task = JoySafeterTask(agent_id=agent.id, prompt="invalid material", status="pending", user_id=user.id)
    db_session.add_all([project, session, task])
    await db_session.flush()

    if surface == "managed_credential":
        row = JoySafeterCredential(
            project_id=project.id,
            kind="service",
            name="invalid-service",
            data={"TOKEN": "plaintext-must-not-be-rewrapped"},
        )
    elif surface == "managed_oauth":
        group = JoySafeterCredentialGroup(project_id=project.id, name="invalid-oauth-group")
        db_session.add(group)
        await db_session.flush()
        row = JoySafeterCredential(
            project_id=project.id,
            kind="mcp",
            name="invalid-oauth",
            data={},
            mcp_server_url="https://mcp.example.com",
            normalized_mcp_server_url="https://mcp.example.com/",
            credential_type="oauth",
            oauth_config={"client_secret": "plaintext-must-not-be-rewrapped"},
            group_id=group.id,
        )
    elif surface == "task_identity":
        now = utc_now()
        row = JoySafeterTaskIdentityContext(
            task_id=task.id,
            project_id=project.id,
            user_id=str(user.id),
            credential_kind="identity_token",
            encrypted_credential="plaintext-must-not-be-rewrapped",
            captured_at=now,
            expires_at=now + timedelta(minutes=10),
        )
    else:
        row = JoySafeterSessionRepo(
            session_id=session.id,
            url="https://github.com/example/private.git",
            branch="main",
            mount_path="/workspace/private",
            mount_name="private",
            encrypted_token="plaintext-must-not-be-rewrapped",
            token_expires_at=utc_now() + timedelta(minutes=10),
            token_rotated_at=utc_now(),
        )
    db_session.add(row)
    await db_session.commit()

    with pytest.raises(CredentialCiphertextError, match=expected_location):
        await rewrap_sensitive_material(db_session, protector, limit_per_store=1)

    if surface == "managed_credential":
        assert row.data["TOKEN"] == "plaintext-must-not-be-rewrapped"
    elif surface == "managed_oauth":
        assert row.oauth_config["client_secret"] == "plaintext-must-not-be-rewrapped"
    elif surface == "task_identity":
        assert row.encrypted_credential == "plaintext-must-not-be-rewrapped"
    else:
        assert row.encrypted_token == "plaintext-must-not-be-rewrapped"


@pytest.mark.asyncio
async def test_rewrap_rolls_back_earlier_store_changes_when_a_later_store_fails(db_session):
    legacy = CredentialCipher(LEGACY_KEY)
    protector = VersionedMaterialProtector(
        LEGACY_KEY,
        keyring_json=KEYRING,
        write_key_id="active-2026-08",
    )
    project = await _create_project(db_session)
    user = AuthUser(name="Atomic Rewrap User", email=f"atomic-{uuid.uuid4()}@example.com")
    agent = JoySafeterAgent(name=f"atomic-agent-{uuid.uuid4()}")
    db_session.add_all([user, agent])
    await db_session.flush()
    task = JoySafeterTask(agent_id=agent.id, prompt="atomic rewrap", status="pending", user_id=user.id)
    credential = JoySafeterCredential(
        project_id=project.id,
        kind="service",
        name="atomic-rewrap-service",
        data={"TOKEN": legacy.encrypt("must-stay-v1")},
    )
    db_session.add_all([task, credential])
    await db_session.flush()
    identity = JoySafeterTaskIdentityContext(
        task_id=task.id,
        project_id=project.id,
        user_id=str(user.id),
        credential_kind="identity_token",
        encrypted_credential="plaintext-must-fail",
        captured_at=utc_now(),
        expires_at=utc_now() + timedelta(minutes=10),
    )
    db_session.add(identity)
    await db_session.commit()

    with pytest.raises(CredentialCiphertextError, match="task_identity"):
        await rewrap_sensitive_material(db_session, protector, limit_per_store=10)

    await db_session.commit()
    await db_session.refresh(credential)
    assert credential.data["TOKEN"].startswith("enc:v1:")


@pytest.mark.asyncio
async def test_integrity_verifier_detects_active_key_corruption_missed_by_inventory_and_rewrap(
    db_session,
):
    cipher = _rotation_cipher()
    protector = VersionedMaterialProtector(
        LEGACY_KEY,
        keyring_json=KEYRING,
        write_key_id="active-2026-08",
    )
    organization = Organization(name=f"integrity-org-{uuid.uuid4()}", slug=f"integrity-{uuid.uuid4()}")
    user = AuthUser(name="Integrity User", email=f"integrity-{uuid.uuid4()}@example.com")
    agent = JoySafeterAgent(name=f"integrity-agent-{uuid.uuid4()}")
    db_session.add_all([organization, user, agent])
    await db_session.flush()
    project = Project(org_id=organization.id, name="Integrity Project", slug=f"integrity-{uuid.uuid4()}")
    db_session.add(project)
    await db_session.flush()
    group = JoySafeterCredentialGroup(project_id=project.id, name="integrity-oauth-group")
    session = JoySafeterSession(agent_id=agent.id, status="idle")
    task = JoySafeterTask(agent_id=agent.id, prompt="integrity", status="pending", user_id=user.id)
    db_session.add_all([group, session, task])
    await db_session.flush()

    damaged = {
        "managed": _damage_ciphertext(cipher.encrypt("managed-secret-must-not-leak")),
        "client_secret": _damage_ciphertext(cipher.encrypt("oauth-client-secret-must-not-leak")),
        "refresh_token": _damage_ciphertext(cipher.encrypt("oauth-refresh-token-must-not-leak")),
        "identity": _damage_ciphertext(cipher.encrypt("identity-secret-must-not-leak")),
        "repository": _damage_ciphertext(cipher.encrypt("repository-secret-must-not-leak")),
    }
    now = utc_now()
    db_session.add_all(
        [
            JoySafeterCredential(
                project_id=project.id,
                kind="service",
                name="damaged-managed",
                data={"TOKEN": damaged["managed"]},
            ),
            JoySafeterCredential(
                project_id=project.id,
                kind="mcp",
                name="damaged-oauth",
                data={},
                mcp_server_url="https://mcp.example.com",
                normalized_mcp_server_url="https://mcp.example.com/",
                credential_type="oauth",
                oauth_config={
                    "client_secret": damaged["client_secret"],
                    "refresh_token": damaged["refresh_token"],
                },
                group_id=group.id,
            ),
            JoySafeterTaskIdentityContext(
                task_id=task.id,
                project_id=project.id,
                user_id=str(user.id),
                credential_kind="identity_token",
                encrypted_credential=damaged["identity"],
                captured_at=now,
                expires_at=now + timedelta(minutes=10),
            ),
            JoySafeterSessionRepo(
                session_id=session.id,
                url="https://github.com/example/damaged.git",
                branch="main",
                mount_path="/workspace/damaged",
                mount_name="damaged",
                encrypted_token=damaged["repository"],
                token_expires_at=now + timedelta(minutes=10),
                token_rotated_at=now,
            ),
        ]
    )
    await db_session.commit()

    await validate_credential_encryption_storage_coverage(db_session, cipher)
    rewrap_result = await rewrap_sensitive_material(db_session, protector, limit_per_store=10)
    assert rewrap_result == rewrap_result.empty()

    before = (
        await db_session.execute(
            text(
                "SELECT "
                "(SELECT jsonb_agg(jsonb_build_array(id, data, oauth_config) ORDER BY id) "
                " FROM joysafeter_credentials), "
                "(SELECT jsonb_agg(jsonb_build_array(task_id, encrypted_credential) ORDER BY task_id) "
                " FROM joysafeter_task_identity_contexts), "
                "(SELECT jsonb_agg(jsonb_build_array(id, encrypted_token) ORDER BY id) "
                " FROM joysafeter_session_repos)"
            )
        )
    ).one()

    result = await verify_sensitive_material_integrity(db_session, protector, batch_size=1)

    after = (
        await db_session.execute(
            text(
                "SELECT "
                "(SELECT jsonb_agg(jsonb_build_array(id, data, oauth_config) ORDER BY id) "
                " FROM joysafeter_credentials), "
                "(SELECT jsonb_agg(jsonb_build_array(task_id, encrypted_credential) ORDER BY task_id) "
                " FROM joysafeter_task_identity_contexts), "
                "(SELECT jsonb_agg(jsonb_build_array(id, encrypted_token) ORDER BY id) "
                " FROM joysafeter_session_repos)"
            )
        )
    ).one()

    assert result.checked_values == 5
    assert result.valid_values == 0
    assert result.invalid_values == 5
    assert {(issue.surface, issue.field, issue.category) for issue in result.issues} == {
        ("managed_credential.data", "TOKEN", "ciphertext-invalid"),
        ("managed_credential.oauth_config", "client_secret", "ciphertext-invalid"),
        ("managed_credential.oauth_config", "refresh_token", "ciphertext-invalid"),
        ("task_identity", "encrypted_credential", "ciphertext-invalid"),
        ("repository_token", "encrypted_token", "ciphertext-invalid"),
    }
    assert all(issue.record_id for issue in result.issues)
    assert before == after
    serialized = json.dumps(asdict(result), sort_keys=True)
    assert all(secret not in serialized for secret in damaged.values())
    assert "must-not-leak" not in serialized
    assert "InvalidTag" not in serialized


@pytest.mark.asyncio
async def test_integrity_verifier_pages_through_every_store(db_session):
    cipher = _rotation_cipher()
    protector = VersionedMaterialProtector(
        LEGACY_KEY,
        keyring_json=KEYRING,
        write_key_id="active-2026-08",
    )
    project = await _create_project(db_session)
    user = AuthUser(name="Paged Integrity User", email=f"paged-{uuid.uuid4()}@example.com")
    agent = JoySafeterAgent(name=f"paged-agent-{uuid.uuid4()}")
    group = JoySafeterCredentialGroup(project_id=project.id, name="paged-oauth-group")
    db_session.add_all([user, agent, group])
    await db_session.flush()
    now = utc_now()

    for index in range(3):
        session = JoySafeterSession(agent_id=agent.id, status="idle")
        task = JoySafeterTask(
            agent_id=agent.id,
            prompt=f"paged-integrity-{index}",
            status="pending",
            user_id=user.id,
        )
        db_session.add_all([session, task])
        await db_session.flush()
        db_session.add_all(
            [
                JoySafeterCredential(
                    project_id=project.id,
                    kind="service",
                    name=f"paged-managed-{index}",
                    data={"TOKEN": cipher.encrypt(f"managed-{index}")},
                ),
                JoySafeterCredential(
                    project_id=project.id,
                    kind="mcp",
                    name=f"paged-oauth-{index}",
                    data={},
                    mcp_server_url=f"https://mcp-{index}.example.com",
                    normalized_mcp_server_url=f"https://mcp-{index}.example.com/",
                    credential_type="oauth",
                    oauth_config={
                        "client_secret": cipher.encrypt(f"client-{index}"),
                        "refresh_token": cipher.encrypt(f"refresh-{index}"),
                    },
                    group_id=group.id,
                ),
                JoySafeterTaskIdentityContext(
                    task_id=task.id,
                    project_id=project.id,
                    user_id=str(user.id),
                    credential_kind="identity_token",
                    encrypted_credential=cipher.encrypt(f"identity-{index}"),
                    captured_at=now,
                    expires_at=now + timedelta(minutes=10),
                ),
                JoySafeterSessionRepo(
                    session_id=session.id,
                    url=f"https://github.com/example/paged-{index}.git",
                    branch="main",
                    mount_path=f"/workspace/paged-{index}",
                    mount_name=f"paged-{index}",
                    encrypted_token=cipher.encrypt(f"repository-{index}"),
                    token_expires_at=now + timedelta(minutes=10),
                    token_rotated_at=now,
                ),
            ]
        )
    await db_session.commit()

    result = await verify_sensitive_material_integrity(db_session, protector, batch_size=1)

    assert result.checked_values == 15
    assert result.valid_values == 15
    assert result.invalid_values == 0
    assert result.issues == ()


@pytest.mark.asyncio
async def test_integrity_verifier_reports_invalid_json_shapes_and_value_types_without_rewriting(
    db_session,
):
    protector = VersionedMaterialProtector(
        LEGACY_KEY,
        keyring_json=KEYRING,
        write_key_id="active-2026-08",
    )
    project = await _create_project(db_session)
    rows = [
        JoySafeterCredential(
            project_id=project.id,
            kind="service",
            name=f"invalid-shape-{index}",
            data={},
        )
        for index in range(4)
    ]
    db_session.add_all(rows)
    await db_session.flush()
    await db_session.execute(
        text("UPDATE joysafeter_credentials SET data = CAST(:value AS jsonb) WHERE id = :id"),
        [
            {"id": rows[0].id.uuid, "value": "[]"},
            {"id": rows[1].id.uuid, "value": "null"},
            {"id": rows[2].id.uuid, "value": '{"TOKEN": 42}'},
            {"id": rows[3].id.uuid, "value": '{"TOKEN": "plaintext-must-not-leak"}'},
        ],
    )
    await db_session.commit()

    before = (await db_session.execute(text("SELECT id, data FROM joysafeter_credentials ORDER BY id"))).all()
    result = await verify_sensitive_material_integrity(db_session, protector, batch_size=2)
    after = (await db_session.execute(text("SELECT id, data FROM joysafeter_credentials ORDER BY id"))).all()

    assert result.checked_values == 4
    assert result.valid_values == 0
    assert result.invalid_values == 4
    assert Counter((issue.field, issue.category) for issue in result.issues) == Counter(
        [
            ("data", "invalid-container-shape"),
            ("data", "invalid-container-shape"),
            ("TOKEN", "invalid-value-type"),
            ("TOKEN", "ciphertext-invalid"),
        ]
    )
    assert before == after
    serialized = json.dumps(asdict(result), sort_keys=True)
    assert "plaintext-must-not-leak" not in serialized


@pytest.mark.no_db
def test_integrity_cli_uses_separate_runner_and_returns_nonzero_for_issues(monkeypatch, capsys):
    from scripts import credential_encryption_rotation

    calls: list[int] = []

    async def fake_run_integrity_verification(*, batch_size: int) -> dict[str, object]:
        calls.append(batch_size)
        return {
            "integrity": {
                "checked_values": 1,
                "valid_values": 0,
                "invalid_values": 1,
                "issues": [
                    {
                        "surface": "managed_credential.data",
                        "record_id": "credential-id",
                        "field": "TOKEN",
                        "category": "ciphertext-invalid",
                    }
                ],
            },
            "status": "failed",
        }

    monkeypatch.setattr(
        credential_encryption_rotation,
        "_run_integrity_verification",
        fake_run_integrity_verification,
    )

    assert credential_encryption_rotation.main(["--verify-integrity", "--integrity-batch-size", "7"]) == 1
    assert calls == [7]
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "failed"
    assert output["integrity"]["issues"][0] == {
        "surface": "managed_credential.data",
        "record_id": "credential-id",
        "field": "TOKEN",
        "category": "ciphertext-invalid",
    }


@pytest.mark.no_db
@pytest.mark.parametrize(
    "arguments",
    [
        ["--verify-integrity", "--initialize-missing-canaries"],
        ["--verify-integrity", "--rewrap-batch", "1"],
        ["--verify-integrity", "--integrity-batch-size", "0"],
    ],
)
def test_integrity_cli_rejects_mutating_or_unbounded_arguments(arguments):
    from scripts import credential_encryption_rotation

    with pytest.raises(SystemExit) as exc_info:
        credential_encryption_rotation.main(arguments)

    assert exc_info.value.code == 2


@pytest.mark.asyncio
async def test_integrity_cli_runner_uses_a_repeatable_read_read_only_transaction(
    postgres_url: str,
    monkeypatch,
):
    from scripts import credential_encryption_rotation

    local_engine = create_async_engine(postgres_url, poolclass=NullPool)
    local_factory = async_sessionmaker(local_engine, class_=AsyncSession, expire_on_commit=False)
    real_verify = credential_encryption_rotation.verify_sensitive_material_integrity

    async def assert_transaction_guards(db, protector, *, batch_size):
        assert await db.scalar(text("SHOW transaction_read_only")) == "on"
        assert await db.scalar(text("SHOW transaction_isolation")) == "repeatable read"
        return await real_verify(db, protector, batch_size=batch_size)

    monkeypatch.setattr(credential_encryption_rotation, "async_session_factory", local_factory)
    monkeypatch.setattr(credential_encryption_rotation, "engine", local_engine)
    monkeypatch.setattr(
        credential_encryption_rotation,
        "verify_sensitive_material_integrity",
        assert_transaction_guards,
    )
    monkeypatch.setattr(credential_encryption_rotation.joysafeter_config, "vault_encryption_key", LEGACY_KEY)
    monkeypatch.setattr(
        credential_encryption_rotation.joysafeter_config,
        "credential_encryption_keyring",
        KEYRING,
    )
    monkeypatch.setattr(
        credential_encryption_rotation.joysafeter_config,
        "credential_encryption_write_key_id",
        "active-2026-08",
    )

    assert await credential_encryption_rotation._run_integrity_verification(batch_size=1) == {
        "integrity": {
            "checked_values": 0,
            "valid_values": 0,
            "invalid_values": 0,
            "issues": (),
        },
        "status": "ok",
    }
