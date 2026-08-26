use std::fs;
use std::path::{Path, PathBuf};

use joysafeter_types::agent::{Agent, ChatSession, SandboxRecord};
use joysafeter_types::environment::Environment;
use joysafeter_types::event::SessionEvent;
use joysafeter_types::memory::{Actor, Memory, MemoryStore, MemoryVersion, SessionMemoryStore};
use joysafeter_types::sandbox::MemoryMount;
use joysafeter_types::session::{Session, SessionAgent, SessionInternal};
use joysafeter_types::task::Task;
use joysafeter_types::{
    AgentId, AgentVersionId, ApiKeyId, CredentialGroupId, CredentialId, EnvironmentId, EventId,
    MemoryId, MemoryStoreId, MemoryVersionId, SandboxId, SessionId, SessionResourceId, TaskId,
};

fn rust_files(root: &Path) -> Vec<PathBuf> {
    let mut files = Vec::new();
    let mut pending = vec![root.to_path_buf()];
    while let Some(directory) = pending.pop() {
        for entry in fs::read_dir(directory).expect("read source directory") {
            let path = entry.expect("read source entry").path();
            if path.is_dir() {
                pending.push(path);
            } else if path.extension().and_then(|value| value.to_str()) == Some("rs") {
                files.push(path);
            }
        }
    }
    files.sort();
    files
}

#[test]
fn production_code_has_no_optional_entity_prefix_parsers() {
    let workspace_root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let prefixes = [
        "agent_",
        "agentver_",
        "apikey_",
        "sess_",
        "task_",
        "trig_",
        "env_",
        "cred_",
        "credgrp_",
        "sbx_",
        "memstore_",
        "mem_",
        "memver_",
        "skill_",
        "sklfile_",
        "sklscan_",
        "sklver_",
        "sklvfile_",
        "skluse_",
        "file_",
        "sesrsc_",
        "evt_",
        "vol_",
        "stgrant_",
        "staudit_",
    ];
    let mut violations = Vec::new();

    for path in rust_files(&workspace_root.join("crates")) {
        if path
            .components()
            .any(|component| component.as_os_str() == "tests")
        {
            continue;
        }
        let source = fs::read_to_string(&path).expect("read Rust source");
        for prefix in prefixes {
            let pattern = format!("strip_prefix(\"{prefix}\").unwrap_or");
            if source.contains(&pattern) {
                violations.push(format!("{}:{pattern}", path.display()));
            }
        }
    }

    assert!(violations.is_empty(), "{}", violations.join("\n"));
}

#[test]
fn all_public_server_owned_ids_are_registered() {
    let _ = (AgentVersionId::new(), ApiKeyId::new());
}

#[test]
fn public_dto_entity_fields_use_canonical_typed_ids() {
    fn agent(value: &Agent) -> (AgentId, Option<EnvironmentId>, Option<CredentialId>) {
        (value.id, value.environment_id, value.model_credential_id)
    }
    fn environment(value: &Environment) -> EnvironmentId {
        value.id
    }
    fn memory_store(value: &MemoryStore) -> MemoryStoreId {
        value.id
    }
    fn memory(value: &Memory) -> (MemoryId, MemoryStoreId, MemoryVersionId) {
        (value.id, value.store_id, value.current_version_id)
    }
    fn memory_version(value: &MemoryVersion) -> (MemoryVersionId, MemoryStoreId, MemoryId) {
        (value.id, value.store_id, value.memory_id)
    }
    fn api_actor(value: &Actor) -> Option<ApiKeyId> {
        match value {
            Actor::ApiActor { api_key_id } => Some(*api_key_id),
            _ => None,
        }
    }
    fn session_memory_store(
        value: &SessionMemoryStore,
    ) -> (SessionResourceId, SessionId, MemoryStoreId) {
        (value.id, value.session_id, value.store_id)
    }
    fn session(value: &Session) -> (SessionId, Vec<CredentialGroupId>) {
        (value.id, value.credential_group_ids.clone())
    }
    fn session_agent(value: &SessionAgent) -> AgentId {
        value.id
    }
    fn session_internal(value: &SessionInternal) -> (AgentId, Option<SandboxId>) {
        (value.agent_id, value.last_sandbox_id)
    }
    fn chat_session(
        value: &ChatSession,
    ) -> (
        SessionId,
        AgentId,
        Option<SandboxId>,
        Vec<CredentialGroupId>,
    ) {
        (
            value.id,
            value.agent_id,
            value.last_sandbox_id,
            value.credential_group_ids.clone(),
        )
    }
    fn sandbox_record(value: &SandboxRecord) -> (SandboxId, Option<SessionId>, Option<TaskId>) {
        (value.id, value.chat_session_id, value.last_task_id)
    }
    fn task(value: &Task) -> (TaskId, AgentId, Option<SessionId>, Option<SandboxId>) {
        (
            value.id,
            value.agent_id,
            value.chat_session_id,
            value.sandbox_id,
        )
    }
    fn event(value: &SessionEvent) -> (EventId, SessionId) {
        (value.id, value.session_id)
    }
    fn memory_mount(value: &MemoryMount) -> MemoryStoreId {
        value.store_id
    }

    let _ = (
        agent,
        environment,
        memory_store,
        memory,
        memory_version,
        api_actor,
        session_memory_store,
        session,
        session_agent,
        session_internal,
        chat_session,
        sandbox_record,
        task,
        event,
        memory_mount,
    );
}

#[test]
fn task_json_requires_canonical_entity_ids() {
    let task_id = TaskId::new();
    let agent_id = AgentId::new();
    let session_id = SessionId::new();
    let sandbox_id = SandboxId::new();
    let value = serde_json::json!({
        "id": task_id,
        "agent_id": agent_id,
        "chat_session_id": session_id,
        "status": "pending",
        "prompt": "inspect",
        "system_prompt": null,
        "sandbox_id": sandbox_id,
        "output": "",
        "error": null,
        "usage": null,
        "timeout_sec": 60,
        "retry_count": 0,
        "max_retries": 0,
        "created_at": "2026-08-25T00:00:00Z",
        "started_at": null,
        "completed_at": null
    });

    let task: Task = serde_json::from_value(value.clone()).expect("canonical task IDs");
    assert_eq!(task.id, task_id);
    assert_eq!(serde_json::to_value(task).unwrap(), value);

    for invalid_id in [task_id.as_uuid().to_string(), agent_id.to_string()] {
        let mut invalid = value.clone();
        invalid["id"] = serde_json::Value::String(invalid_id);
        assert!(serde_json::from_value::<Task>(invalid).is_err());
    }
}
