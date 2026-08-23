use std::env;

use joysafeter_orchestrator::kernel::credentials::material::ManagedCredentialMaterialAdapter;
use joysafeter_orchestrator::kernel::repository_access::material::RepositoryAccessMaterialAdapter;
use joysafeter_orchestrator::kernel::sensitive_material::versioned::VersionedMaterialProtector;
use joysafeter_orchestrator::kernel::task_identity::material::TaskIdentityMaterialAdapter;
use serde_json::json;
use sqlx::postgres::PgPoolOptions;

const KEY_ID: &str = "rust-canary-2026-08";
const KEY: &str = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=";
const ENCRYPTED_CANARY: &str = "enc:v2:rust-canary-2026-08:p9+2vu5Oe3pPnN0CzoDKEDl2UJvPoOgV8r/Ono4Z0WJBxpUY8q9pz03jqamAZLltIfIiqYTJBm0AIbSlMQ4VZh9nut+e10KWQDHnUq/FE4A8yQg2aTjW";
const COVERAGE_ORG_ID: &str = "credential-encryption-rust-test-org";
const COVERAGE_PROJECT_ID: &str = "credential-encryption-rust-test-project";
const COVERAGE_CREDENTIAL_ID: &str = "00000000-0000-7000-8000-000000000001";

fn database_url() -> String {
    env::var("JOYSAFETER_CREDENTIAL_RUNTIME_TEST_DATABASE_URL")
        .or_else(|_| env::var("JOYSAFETER_TEST_DATABASE_URL"))
        .or_else(|_| env::var("DATABASE_URL"))
        .map(|url| url.replace("postgresql+asyncpg://", "postgres://"))
        .expect("a credential runtime test database URL must point to migrated PostgreSQL")
}

#[tokio::test]
async fn rust_validates_python_generated_database_canary() {
    let pool = PgPoolOptions::new()
        .max_connections(1)
        .connect(&database_url())
        .await
        .expect("connect to migrated PostgreSQL test database");
    sqlx::query(
        "INSERT INTO joysafeter_credential_encryption_canaries (key_id, encrypted_canary) \
         VALUES ($1, $2) \
         ON CONFLICT (key_id) DO UPDATE SET encrypted_canary = EXCLUDED.encrypted_canary, updated_at = now()",
    )
    .bind(KEY_ID)
    .bind(ENCRYPTED_CANARY)
    .execute(&pool)
    .await
    .expect("insert Python-generated credential encryption canary");

    env::set_var(
        "JOYSAFETER_CREDENTIAL_ENCRYPTION_KEYRING",
        format!(r#"{{"{KEY_ID}":"{KEY}"}}"#),
    );
    env::set_var("JOYSAFETER_CREDENTIAL_ENCRYPTION_WRITE_KEY_ID", KEY_ID);
    env::remove_var("JOYSAFETER_VAULT_ENCRYPTION_KEY");

    VersionedMaterialProtector::validate_database_state(&pool)
        .await
        .expect("Rust must decrypt the Python-generated canary");

    let managed = ManagedCredentialMaterialAdapter::from_env()
        .reveal(&json!({"TOKEN": ENCRYPTED_CANARY}))
        .expect("managed credential adapter must read v2 material");
    assert_eq!(
        managed.require("TOKEN").unwrap(),
        "joysafeter-credential-encryption-canary:rust-canary-2026-08"
    );
    assert_eq!(
        TaskIdentityMaterialAdapter::from_env()
            .reveal(ENCRYPTED_CANARY)
            .unwrap(),
        "joysafeter-credential-encryption-canary:rust-canary-2026-08"
    );
    assert_eq!(
        RepositoryAccessMaterialAdapter::from_env()
            .reveal_optional(ENCRYPTED_CANARY)
            .unwrap()
            .as_deref(),
        Some("joysafeter-credential-encryption-canary:rust-canary-2026-08")
    );

    sqlx::query("DELETE FROM joysafeter_credentials WHERE id = $1::uuid")
        .bind(COVERAGE_CREDENTIAL_ID)
        .execute(&pool)
        .await
        .expect("remove stale coverage credential");
    sqlx::query("DELETE FROM joysafeter_organization_projects WHERE id = $1")
        .bind(COVERAGE_PROJECT_ID)
        .execute(&pool)
        .await
        .expect("remove stale coverage project");
    sqlx::query("DELETE FROM joysafeter_organizations WHERE id = $1")
        .bind(COVERAGE_ORG_ID)
        .execute(&pool)
        .await
        .expect("remove stale coverage organization");
    sqlx::query(
        "INSERT INTO joysafeter_organizations \
         (id, name, slug, storage_used_bytes, departed_member_usage) \
         VALUES ($1, 'Credential Encryption Rust Test', $2, 0, 0)",
    )
    .bind(COVERAGE_ORG_ID)
    .bind(COVERAGE_ORG_ID)
    .execute(&pool)
    .await
    .expect("insert coverage organization");
    sqlx::query(
        "INSERT INTO joysafeter_organization_projects (id, org_id, name, slug, is_default) \
         VALUES ($1, $2, 'Credential Encryption Rust Test', $3, false)",
    )
    .bind(COVERAGE_PROJECT_ID)
    .bind(COVERAGE_ORG_ID)
    .bind(COVERAGE_PROJECT_ID)
    .execute(&pool)
    .await
    .expect("insert coverage project");
    sqlx::query(
        "INSERT INTO joysafeter_credentials (id, project_id, kind, name, data, is_default) \
         VALUES ($1::uuid, $2, 'service', 'missing-reader-key', \
         '{\"TOKEN\":\"enc:v2:retired-2025-01:AA==\"}'::jsonb, false)",
    )
    .bind(COVERAGE_CREDENTIAL_ID)
    .bind(COVERAGE_PROJECT_ID)
    .execute(&pool)
    .await
    .expect("insert coverage credential");

    let coverage_result = VersionedMaterialProtector::validate_database_state(&pool).await;

    sqlx::query("DELETE FROM joysafeter_credentials WHERE id = $1::uuid")
        .bind(COVERAGE_CREDENTIAL_ID)
        .execute(&pool)
        .await
        .expect("remove coverage credential");

    assert!(coverage_result
        .expect_err("Rust startup must reject an unconfigured referenced key id")
        .to_string()
        .contains("enc:v2:retired-2025-01"));

    sqlx::query(
        "INSERT INTO joysafeter_credentials (id, project_id, kind, name, data, is_default) \
         VALUES ($1::uuid, $2, 'service', 'invalid-json-shape', '[]'::jsonb, false)",
    )
    .bind(COVERAGE_CREDENTIAL_ID)
    .bind(COVERAGE_PROJECT_ID)
    .execute(&pool)
    .await
    .expect("insert invalid-shape coverage credential");

    let invalid_shape_result = VersionedMaterialProtector::validate_database_state(&pool).await;

    sqlx::query("DELETE FROM joysafeter_credentials WHERE id = $1::uuid")
        .bind(COVERAGE_CREDENTIAL_ID)
        .execute(&pool)
        .await
        .expect("remove invalid-shape coverage credential");

    assert!(invalid_shape_result
        .expect_err("Rust startup must reject non-object credential JSON")
        .to_string()
        .contains("invalid-or-plaintext"));

    sqlx::query("DELETE FROM joysafeter_credential_encryption_canaries WHERE key_id = $1")
        .bind(KEY_ID)
        .execute(&pool)
        .await
        .expect("remove test canary");
    sqlx::query("DELETE FROM joysafeter_organization_projects WHERE id = $1")
        .bind(COVERAGE_PROJECT_ID)
        .execute(&pool)
        .await
        .expect("remove coverage project");
    sqlx::query("DELETE FROM joysafeter_organizations WHERE id = $1")
        .bind(COVERAGE_ORG_ID)
        .execute(&pool)
        .await
        .expect("remove coverage organization");
}
