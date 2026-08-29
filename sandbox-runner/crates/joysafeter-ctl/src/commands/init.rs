use crate::client::JoysafeterClient;
use anyhow::{bail, Context};
use base64::Engine as _;
use dialoguer::{Confirm, Input, Select};
use joysafeter_entity_id::{AgentId, CredentialId, EnvironmentId, MemoryStoreId, SessionId};
use joysafeter_types::agent::EngineKind;
use std::path::Path;

use super::mcp_authorization::{
    authorize_session_interactively, build_session_body, SessionAuthorization,
};

#[derive(Default)]
enum StepResult<T> {
    UsedExisting,
    Created {
        id: T,
        name: String,
    },
    #[default]
    Skipped,
}

#[derive(Default)]
struct WizardState {
    credential_name: String,
    credential_id: Option<CredentialId>,
    credential_result: StepResult<CredentialId>,

    env_name: String,
    env_id: Option<EnvironmentId>,
    env_result: StepResult<EnvironmentId>,

    agent_id: Option<AgentId>,
    agent: Option<serde_json::Value>,
    agent_result: StepResult<AgentId>,

    mcp_authorization: SessionAuthorization,

    memory_store_resources: Vec<serde_json::Value>,
    memory_store_id: Option<MemoryStoreId>,
    memory_store_result: StepResult<MemoryStoreId>,

    session_id: Option<SessionId>,
    session_result: StepResult<SessionId>,
}

#[derive(PartialEq)]
enum StepAction {
    Completed,
    Back,
}

pub async fn run(client: &JoysafeterClient) -> anyhow::Result<()> {
    println!("╔═══════════════════════════════════════════════════╗");
    println!("║     joysafeterctl init — Full Setup Wizard        ║");
    println!("╠═══════════════════════════════════════════════════╣");
    println!("║  This wizard will guide you through creating:    ║");
    println!("║    1. Credential   (model API access)            ║");
    println!("║    2. Environment  (sandbox config)              ║");
    println!("║    3. Agent        (model + tools)               ║");
    println!("║    4. MCP Access   (per-session authorization)   ║");
    println!("║    5. Memory Store (persistent memory, optional) ║");
    println!("║    6. Session      (conversation)                ║");
    println!("║    7. Event        (first message)               ║");
    println!("╚═══════════════════════════════════════════════════╝");
    println!();

    let mut step: usize = 1;
    let mut state = WizardState::default();

    loop {
        let action = match step {
            1 => run_step_credential(client, &mut state, true).await?,
            2 => run_step_environment(client, &mut state, true).await?,
            3 => run_step_agent(client, &mut state, true).await?,
            4 => run_step_mcp_authorization(client, &mut state, true).await?,
            5 => run_step_memory_store(client, &mut state, true).await?,
            6 => run_step_session(client, &mut state, true).await?,
            7 => {
                let action = run_step_event(client, &mut state, true).await?;
                if action == StepAction::Completed {
                    break;
                }
                action
            }
            _ => break,
        };

        match action {
            StepAction::Completed => step += 1,
            StepAction::Back => {
                rollback_step(client, step, &mut state).await?;
                if step == 1 {
                    println!("  Wizard cancelled.");
                    return Ok(());
                }
                step -= 1;
            }
        }
    }

    // ── Summary ─────────────────────────────────────────
    println!();
    println!("╔═══════════════════════════════════════════════════╗");
    println!("║                  Setup Complete                   ║");
    println!("╠═══════════════════════════════════════════════════╣");
    if !state.credential_name.is_empty() {
        println!("║  Credential:  {:<36} ║", state.credential_name);
    }
    println!("║  Environment: {:<36} ║", state.env_name);
    println!(
        "║  Agent ID:    {:<36} ║",
        state.agent_id.map(|id| id.to_string()).unwrap_or_default()
    );
    println!(
        "║  MCP groups:  {:<36} ║",
        state.mcp_authorization.credential_group_ids.len()
    );
    println!(
        "║  Session ID:  {:<36} ║",
        state
            .session_id
            .map(|id| id.to_string())
            .unwrap_or_default()
    );
    println!("╚═══════════════════════════════════════════════════╝");

    // ── Enter chat mode ────────────────────────────────
    println!();
    println!("Entering chat mode...");
    let session_id = state.session_id.context("setup did not create a session")?;
    super::chat::run(client, Some(session_id), None, &[], 2).await
}

async fn rollback_step(
    client: &JoysafeterClient,
    step: usize,
    state: &mut WizardState,
) -> anyhow::Result<()> {
    match step {
        1 => {
            if let StepResult::Created { id, ref name } = state.credential_result {
                println!("  \u{21a9} Deleting credential/{} ...", name);
                client.delete_credential(id).await.ok();
            }
            state.credential_name.clear();
            state.credential_id = None;
            state.credential_result = StepResult::Skipped;
        }
        2 => {
            if let StepResult::Created { id, ref name } = state.env_result {
                println!("  \u{21a9} Deleting environment/{} ...", name);
                client.delete_environment(id).await.ok();
            }
            state.env_name.clear();
            state.env_id = None;
            state.env_result = StepResult::Skipped;
        }
        3 => {
            if let StepResult::Created { id, .. } = state.agent_result {
                println!("  \u{21a9} Deleting agent/{} ...", id);
                client.delete_agent(id, true).await.ok();
            }
            state.agent_id = None;
            state.agent = None;
            state.agent_result = StepResult::Skipped;
        }
        4 => {
            state.mcp_authorization.rollback_created(client).await;
        }
        5 => {
            if let StepResult::Created { id, ref name } = state.memory_store_result {
                println!("  \u{21a9} Deleting memorystore/{} ...", name);
                client.delete_memory_store(id).await.ok();
            }
            state.memory_store_resources.clear();
            state.memory_store_id = None;
            state.memory_store_result = StepResult::Skipped;
        }
        6 => {
            if let StepResult::Created { id, .. } = state.session_result {
                println!("  \u{21a9} Deleting session/{} ...", id);
                client.delete_session(id).await.ok();
            }
            state.session_id = None;
            state.session_result = StepResult::Skipped;
        }
        // Step 7 (first event) only appends an append-only session event; it
        // creates nothing deletable, so navigating Back must NOT touch the
        // session created in step 6.
        7 => {}
        _ => {}
    }
    Ok(())
}

// ── Step 1: Credential ──────────────────────────────────────────

async fn run_step_credential(
    client: &JoysafeterClient,
    state: &mut WizardState,
    allow_back: bool,
) -> anyhow::Result<StepAction> {
    println!("\x1b[1;36m━━━ Step 1/7: Model Credential ━━━\x1b[0m\n");

    let existing = client
        .list_credentials()
        .await
        .unwrap_or_default()
        .into_iter()
        .filter(|credential| credential["kind"].as_str() == Some("model"))
        .collect::<Vec<_>>();
    let choice = pick_or_create("model credential", &existing, "name", allow_back, true)?;
    match choice {
        PickResult::Existing { id, name } => {
            let credential_id = id
                .parse::<CredentialId>()
                .context("credential response contained a non-canonical id")?;
            println!("  Using existing credential: {} ({})", name, credential_id);
            state.credential_name = name;
            state.credential_id = Some(credential_id);
            state.credential_result = StepResult::UsedExisting;
        }
        PickResult::Create => {
            let name = input_required("Credential name")?;
            let mut data = serde_json::Map::new();

            let providers = [
                "Claude (Anthropic)",
                "Codex (OpenAI)",
                "Custom (manual key-value pairs)",
            ];
            let provider_idx = Select::new()
                .with_prompt("Provider")
                .items(&providers)
                .default(0)
                .interact()?;

            let (provider, protocol) = match provider_idx {
                0 => {
                    let auth_types = [
                        "ANTHROPIC_API_KEY (x-api-key header, recommended for most proxies)",
                        "ANTHROPIC_AUTH_TOKEN (Authorization: Bearer header)",
                    ];
                    let auth_idx = Select::new()
                        .with_prompt("Authentication type")
                        .items(&auth_types)
                        .default(0)
                        .interact()?;
                    let auth_key = if auth_idx == 0 {
                        "ANTHROPIC_API_KEY"
                    } else {
                        "ANTHROPIC_AUTH_TOKEN"
                    };
                    let auth_val: String = Input::new().with_prompt(auth_key).interact_text()?;
                    if !auth_val.trim().is_empty() {
                        data.insert(
                            auth_key.to_string(),
                            serde_json::Value::String(auth_val.trim().to_string()),
                        );
                    }
                    let base_url: String = Input::new()
                        .with_prompt("ANTHROPIC_BASE_URL (API base URL, empty for default)")
                        .allow_empty(true)
                        .interact_text()?;
                    if !base_url.trim().is_empty() {
                        data.insert(
                            "ANTHROPIC_BASE_URL".to_string(),
                            serde_json::Value::String(base_url.trim().to_string()),
                        );
                    }
                    ("anthropic".to_string(), "anthropic_messages".to_string())
                }
                1 => {
                    let api_key: String =
                        Input::new().with_prompt("OPENAI_API_KEY").interact_text()?;
                    if !api_key.trim().is_empty() {
                        data.insert(
                            "OPENAI_API_KEY".to_string(),
                            serde_json::Value::String(api_key.trim().to_string()),
                        );
                    }
                    let base_url: String = Input::new()
                        .with_prompt("OPENAI_BASE_URL (API base URL, empty for default: https://api.openai.com/v1)")
                        .allow_empty(true)
                        .interact_text()?;
                    if !base_url.trim().is_empty() {
                        data.insert(
                            "OPENAI_BASE_URL".to_string(),
                            serde_json::Value::String(base_url.trim().to_string()),
                        );
                    }
                    let model: String = Input::new()
                        .with_prompt("OPENAI_MODEL (empty for default: gpt-5.3-codex)")
                        .allow_empty(true)
                        .interact_text()?;
                    if !model.trim().is_empty() {
                        data.insert(
                            "OPENAI_MODEL".to_string(),
                            serde_json::Value::String(model.trim().to_string()),
                        );
                    }
                    let effort: String = Input::new()
                        .with_prompt("OPENAI_REASONING_EFFORT (empty for default: high)")
                        .allow_empty(true)
                        .interact_text()?;
                    if !effort.trim().is_empty() {
                        data.insert(
                            "OPENAI_REASONING_EFFORT".to_string(),
                            serde_json::Value::String(effort.trim().to_string()),
                        );
                    }
                    ("openai".to_string(), "openai_responses".to_string())
                }
                _ => (
                    input_required("Provider ID")?,
                    input_required("Protocol ID")?,
                ),
            };

            if Confirm::new()
                .with_prompt("Add more key-value pairs?")
                .default(false)
                .interact()?
            {
                loop {
                    let key = input_required("Key name")?;
                    let val: String = Input::new()
                        .with_prompt(format!("Value for {}", key))
                        .interact_text()?;
                    data.insert(key, serde_json::Value::String(val));
                    if !Confirm::new()
                        .with_prompt("Add another?")
                        .default(false)
                        .interact()?
                    {
                        break;
                    }
                }
            }
            if data.is_empty() {
                bail!("Credential must have at least one key-value pair");
            }
            let body = serde_json::json!({
                "kind": "model",
                "name": name,
                "provider": provider,
                "protocol": protocol,
                "is_default": Confirm::new()
                    .with_prompt("Set as default model credential?")
                    .default(false)
                    .interact()?,
                "data": serde_json::Value::Object(data),
            });
            let resp = client.create_credential(&body).await?;
            let id = resp["id"]
                .as_str()
                .context("credential response missing id")?
                .parse::<CredentialId>()
                .context("credential response contained a non-canonical id")?;
            println!("  \x1b[0;32m✓\x1b[0m credential/{} created ({})", name, id);
            state.credential_name = name.clone();
            state.credential_id = Some(id);
            state.credential_result = StepResult::Created { id, name };
        }
        PickResult::Skip => {
            println!("  Skipped.");
            state.credential_name.clear();
            state.credential_id = None;
            state.credential_result = StepResult::Skipped;
        }
        PickResult::Back => return Ok(StepAction::Back),
    }
    Ok(StepAction::Completed)
}

// ── Step 2: Environment ─────────────────────────────────────────

async fn run_step_environment(
    client: &JoysafeterClient,
    state: &mut WizardState,
    allow_back: bool,
) -> anyhow::Result<StepAction> {
    println!("\n\x1b[1;36m━━━ Step 2/7: Environment ━━━\x1b[0m\n");

    let existing = client.list_environments().await.unwrap_or_default();
    let choice = pick_or_create("environment", &existing, "name", allow_back, true)?;
    match choice {
        PickResult::Back => return Ok(StepAction::Back),
        PickResult::Existing { id, name } => {
            state.env_id = Some(
                id.parse::<EnvironmentId>()
                    .context("environment response contained a non-canonical id")?,
            );
            state.env_name = name;
            state.env_result = StepResult::UsedExisting;
            println!("  Using existing environment: {}", state.env_name);
        }
        PickResult::Create => {
            let name = input_required("Environment name")?;
            let network_types = vec!["unrestricted", "limited"];
            let net_idx = Select::new()
                .with_prompt("Networking type")
                .items(&network_types)
                .default(0)
                .interact()?;
            let network_type = network_types[net_idx];

            let mut allowed_hosts: Vec<String> = Vec::new();
            if network_type == "limited" {
                loop {
                    let host: String = Input::new()
                        .with_prompt("Allowed host (Enter to finish)")
                        .allow_empty(true)
                        .interact_text()?;
                    if host.trim().is_empty() {
                        break;
                    }
                    allowed_hosts.push(host.trim().to_string());
                }
            }

            let mut networking = serde_json::json!({"type": network_type});
            if !allowed_hosts.is_empty() {
                networking["allowed_hosts"] = serde_json::json!(allowed_hosts);
            }
            let body = serde_json::json!({
                "name": name,
                "config": { "type": "cloud", "networking": networking },
            });
            let resp = client.create_environment(&body).await?;
            let id = resp["id"]
                .as_str()
                .context("environment response missing id")?
                .parse::<EnvironmentId>()
                .context("environment response contained a non-canonical id")?;
            println!("  \x1b[0;32m✓\x1b[0m environment/{} created", name);
            state.env_id = Some(id);
            state.env_name = name.clone();
            state.env_result = StepResult::Created { id, name };
        }
        PickResult::Skip => {
            state.env_result = StepResult::Skipped;
            println!("  Skipped");
        }
    }
    Ok(StepAction::Completed)
}

// ── Step 3: Agent ───────────────────────────────────────────────

async fn run_step_agent(
    client: &JoysafeterClient,
    state: &mut WizardState,
    allow_back: bool,
) -> anyhow::Result<StepAction> {
    println!("\n\x1b[1;36m━━━ Step 3/7: Agent ━━━\x1b[0m\n");

    let existing = client.list_agents().await?;
    let choice = pick_or_create("agent", &existing, "name", allow_back, false)?;
    match choice {
        PickResult::Back => return Ok(StepAction::Back),
        PickResult::Existing { id, name } => {
            let agent_id = id
                .parse::<AgentId>()
                .context("agent response contained a non-canonical id")?;
            state.agent_id = Some(agent_id);
            state.agent = existing
                .iter()
                .find(|agent| agent.get("id").and_then(serde_json::Value::as_str) == Some(&id))
                .cloned();
            state.agent_result = StepResult::UsedExisting;
            println!("  Using existing agent: {} ({})", name, agent_id);
        }
        PickResult::Create => {
            let name = input_required("Agent name")?;
            let engines = EngineKind::ALL.map(|engine| engine.as_str());
            let engine_idx = Select::new()
                .with_prompt("Engine")
                .items(&engines)
                .default(0)
                .interact()?;
            let engine = engines[engine_idx];

            let model = input_required("Model (e.g. Claude-Sonnet-4.6)")?;
            let description = input_optional("Description (optional)")?;
            let system_prompt = input_optional("System prompt (optional)")?;

            let policies = vec!["always_allow", "always_ask"];
            let policy_idx = Select::new()
                .with_prompt("Tool permission policy")
                .items(&policies)
                .default(0)
                .interact()?;
            let policy = policies[policy_idx];

            let skills_packed = collect_packed_items("skill", ".claude/skills/")?;
            let agents_packed = collect_packed_items("agent", ".claude/agents/")?;
            let commands_packed = collect_packed_items("command", ".claude/commands/")?;
            let mcp_servers = super::create::collect_mcp_servers()?;
            let custom_tools = super::create::collect_custom_tools()?;

            let mut body = serde_json::json!({
                "name": name,
                "engine_kind": engine,
                "model": model,
                "tools": [{
                    "type": "agent_toolset_20260401",
                    "default_config": {
                        "permission_policy": { "type": policy }
                    }
                }],
            });
            if let Some(desc) = description {
                body["description"] = serde_json::Value::String(desc);
            }
            if let Some(sp) = system_prompt {
                body["system"] = serde_json::Value::String(sp);
            }
            if !skills_packed.is_empty() {
                body["skills"] = serde_json::json!(skills_packed);
            }
            if !agents_packed.is_empty() {
                body["agents"] = serde_json::json!(agents_packed);
            }
            if !commands_packed.is_empty() {
                body["commands"] = serde_json::json!(commands_packed);
            }
            if let Some(credential_id) = state.credential_id {
                body["model_credential_id"] = serde_json::json!(credential_id);
                println!("  Auto-linking credential: {}", credential_id);
            }
            if let Some(environment_id) = state.env_id {
                body["environment_id"] = serde_json::json!(environment_id);
                println!("  Auto-linking environment: {}", environment_id);
            }
            if !mcp_servers.is_empty() {
                body["mcp_servers"] = serde_json::json!(mcp_servers);
                let tools = body["tools"].as_array_mut().unwrap();
                for s in &mcp_servers {
                    let server_name = s["name"].as_str().unwrap();
                    tools.push(serde_json::json!({
                        "type": "mcp_toolset",
                        "mcp_server_name": server_name
                    }));
                }
            }
            if !custom_tools.is_empty() {
                let tools = body["tools"].as_array_mut().unwrap();
                for t in &custom_tools {
                    tools.push(t.clone());
                }
            }

            let resp = client.create_agent(&body).await?;
            let id = resp["id"]
                .as_str()
                .context("agent response missing id")?
                .parse::<AgentId>()
                .context("agent response contained a non-canonical id")?;
            println!("  \x1b[0;32m✓\x1b[0m agent/{} created ({})", name, id);
            state.agent_id = Some(id);
            state.agent = Some(resp);
            state.agent_result = StepResult::Created { id, name };
        }
        PickResult::Skip => {
            state.agent_result = StepResult::Skipped;
            println!("  Skipped");
        }
    }
    Ok(StepAction::Completed)
}

// ── Step 4: MCP Authorization ───────────────────────────────────

async fn run_step_mcp_authorization(
    client: &JoysafeterClient,
    state: &mut WizardState,
    allow_back: bool,
) -> anyhow::Result<StepAction> {
    println!("\n\x1b[1;36m━━━ Step 4/7: MCP Authorization ━━━\x1b[0m\n");
    if allow_back {
        let options = ["Review MCP authorization", "\u{2190} Back to Agent"];
        let index = Select::new()
            .with_prompt("MCP authorization")
            .items(&options)
            .default(0)
            .interact()?;
        if index == 1 {
            return Ok(StepAction::Back);
        }
    }

    let agent = state.agent.as_ref().context("setup requires an agent")?;
    if !authorize_session_interactively(client, agent, &mut state.mcp_authorization).await? {
        return Ok(StepAction::Back);
    }
    Ok(StepAction::Completed)
}

// ── Step 5: Memory Store ────────────────────────────────────────

async fn run_step_memory_store(
    client: &JoysafeterClient,
    state: &mut WizardState,
    allow_back: bool,
) -> anyhow::Result<StepAction> {
    println!("\n\x1b[1;36m━━━ Step 5/7: Memory Store (optional) ━━━\x1b[0m\n");

    let existing = client.list_memory_stores().await.unwrap_or_default();
    let choice = pick_or_create("memory store", &existing, "name", allow_back, true)?;
    match choice {
        PickResult::Back => return Ok(StepAction::Back),
        PickResult::Existing { id, name } => {
            let store_id = id
                .parse::<MemoryStoreId>()
                .context("memory store response contained a non-canonical id")?;
            let access_opts = ["read_write", "read_only"];
            let access_idx = Select::new()
                .with_prompt("Access mode")
                .items(&access_opts)
                .default(0)
                .interact()?;
            state.memory_store_resources = vec![serde_json::json!({
                "type": "memory_store",
                "memory_store_id": store_id,
                "access": access_opts[access_idx],
            })];
            println!(
                "  Using memory store: {} ({})",
                name, access_opts[access_idx]
            );
            state.memory_store_id = Some(store_id);
            state.memory_store_result = StepResult::UsedExisting;
        }
        PickResult::Create => {
            let name = input_required("Memory store name")?;
            let description = input_optional("Description (optional)")?;
            let mut body = serde_json::json!({ "name": name });
            if let Some(desc) = description {
                body["description"] = serde_json::Value::String(desc);
            }
            let resp = client.create_memory_store(&body).await?;
            let id = resp["id"]
                .as_str()
                .context("memory store response missing id")?
                .parse::<MemoryStoreId>()
                .context("memory store response contained a non-canonical id")?;
            println!("  \x1b[0;32m✓\x1b[0m memorystore/{} created", name);
            state.memory_store_resources = vec![serde_json::json!({
                "type": "memory_store",
                "memory_store_id": id,
                "access": "read_write",
            })];
            state.memory_store_id = Some(id);
            state.memory_store_result = StepResult::Created { id, name };
        }
        PickResult::Skip => {
            println!("  Skipped.");
            state.memory_store_resources.clear();
            state.memory_store_id = None;
            state.memory_store_result = StepResult::Skipped;
        }
    }
    Ok(StepAction::Completed)
}

// ── Step 6: Session ─────────────────────────────────────────────

async fn run_step_session(
    client: &JoysafeterClient,
    state: &mut WizardState,
    allow_back: bool,
) -> anyhow::Result<StepAction> {
    println!("\n\x1b[1;36m━━━ Step 6/7: Session ━━━\x1b[0m\n");

    if allow_back {
        let options = vec![
            "Continue creating session",
            "\u{2190} Back to previous step",
        ];
        let idx = Select::new()
            .with_prompt("Session")
            .items(&options)
            .default(0)
            .interact()?;
        if idx == 1 {
            return Ok(StepAction::Back);
        }
    }

    let title = input_optional("Session title (optional)")?;

    let agent_id = state.agent_id.context("setup requires an agent")?;
    let session_body = build_session_body(
        agent_id,
        state.env_id,
        title.as_deref(),
        &state.memory_store_resources,
        &state.mcp_authorization.credential_group_ids,
    );

    let resp = state
        .mcp_authorization
        .create_session_with_rollback(client, &session_body)
        .await?;
    let id = resp["id"]
        .as_str()
        .context("session response missing id")?
        .parse::<SessionId>()
        .context("session response contained a non-canonical id")?;
    println!("  \x1b[0;32m✓\x1b[0m session/{} created", id);
    state.session_id = Some(id);
    state.session_result = StepResult::Created {
        id,
        name: String::new(),
    };
    Ok(StepAction::Completed)
}

// ── Step 7: First Event ─────────────────────────────────────────

async fn run_step_event(
    client: &JoysafeterClient,
    state: &mut WizardState,
    allow_back: bool,
) -> anyhow::Result<StepAction> {
    println!("\n\x1b[1;36m━━━ Step 7/7: Send First Message ━━━\x1b[0m\n");

    if allow_back {
        let options = vec![
            "Continue to send first message",
            "\u{2190} Back to previous step",
        ];
        let idx = Select::new()
            .with_prompt("Event")
            .items(&options)
            .default(0)
            .interact()?;
        if idx == 1 {
            return Ok(StepAction::Back);
        }
    }

    let send_msg = Confirm::new()
        .with_prompt("Send a first message to the agent?")
        .default(true)
        .interact()?;

    if send_msg {
        let content = input_required("Message content")?;
        let event_body = serde_json::json!({
            "type": "user.message",
            "content": [{"type": "text", "text": content}],
        });
        let session_id = state.session_id.context("setup did not create a session")?;
        client.send_event(session_id, &event_body).await?;
        println!("  \x1b[0;32m✓\x1b[0m event sent to session/{}", session_id);
    } else {
        println!("  Skipped. You can send events later:");
        println!("    joysafeterctl create event");
    }
    Ok(StepAction::Completed)
}

// ── Helpers ─────────────────────────────────────────────────────

enum PickResult {
    Existing { id: String, name: String },
    Create,
    Skip,
    Back,
}

fn pick_or_create(
    resource: &str,
    existing: &[serde_json::Value],
    name_field: &str,
    allow_back: bool,
    skippable: bool,
) -> anyhow::Result<PickResult> {
    if existing.is_empty() {
        let mut options = Vec::new();
        if skippable {
            options.push("Skip (not required)".to_string());
        }
        options.push(format!("+ Create new {}", resource));
        if allow_back {
            options.push("\u{2190} Back to previous step".to_string());
        }
        let idx = Select::new()
            .with_prompt(format!("No existing {}s found", resource))
            .items(&options)
            .default(0)
            .interact()?;
        if allow_back && idx == options.len() - 1 {
            return Ok(PickResult::Back);
        }
        if skippable && idx == 0 {
            return Ok(PickResult::Skip);
        }
        let create_idx = if skippable { 1 } else { 0 };
        if idx == create_idx {
            return Ok(PickResult::Create);
        }
        return Ok(PickResult::Create);
    }

    let mut labels = Vec::new();
    if skippable {
        labels.push("Skip (not required)".to_string());
    }
    for item in existing {
        labels.push(item[name_field].as_str().unwrap_or("?").to_string());
    }
    labels.push(format!("+ Create new {}", resource));
    if allow_back {
        labels.push("\u{2190} Back to previous step".to_string());
    }

    let idx = Select::new()
        .with_prompt(format!("Select or create {}", resource))
        .items(&labels)
        .default(0)
        .interact()?;

    if allow_back && idx == labels.len() - 1 {
        return Ok(PickResult::Back);
    }

    let existing_offset = if skippable { 1 } else { 0 };
    let create_idx = existing_offset + existing.len();

    if skippable && idx == 0 {
        Ok(PickResult::Skip)
    } else if idx == create_idx {
        Ok(PickResult::Create)
    } else {
        let selected = &existing[idx - existing_offset];
        let id = selected["id"]
            .as_str()
            .context("selected resource response missing id")?
            .to_string();
        let name = selected[name_field]
            .as_str()
            .context("selected resource response missing display name")?
            .to_string();
        Ok(PickResult::Existing { id, name })
    }
}

fn input_required(prompt: &str) -> anyhow::Result<String> {
    let val: String = Input::new().with_prompt(prompt).interact_text()?;
    if val.trim().is_empty() {
        bail!("{} cannot be empty", prompt);
    }
    Ok(val.trim().to_string())
}

fn input_optional(prompt: &str) -> anyhow::Result<Option<String>> {
    let val: String = Input::new()
        .with_prompt(prompt)
        .allow_empty(true)
        .interact_text()?;
    if val.trim().is_empty() {
        Ok(None)
    } else {
        Ok(Some(val.trim().to_string()))
    }
}

fn pack_dir(path: &Path) -> anyhow::Result<String> {
    anyhow::ensure!(path.is_dir(), "Not a directory: {}", path.display());
    let mut buf = Vec::new();
    {
        let gz = flate2::write::GzEncoder::new(&mut buf, flate2::Compression::default());
        let mut tar = tar::Builder::new(gz);
        tar.append_dir_all(".", path)
            .with_context(|| format!("Failed to tar: {}", path.display()))?;
        tar.into_inner()?.finish()?;
    }
    Ok(base64::engine::general_purpose::STANDARD.encode(&buf))
}

fn collect_packed_items(label: &str, hint: &str) -> anyhow::Result<Vec<serde_json::Value>> {
    let add = Confirm::new()
        .with_prompt(format!(
            "Add {} directories? (packed to sandbox {})",
            label, hint
        ))
        .default(false)
        .interact()?;
    if !add {
        return Ok(Vec::new());
    }

    let mut items = Vec::new();
    loop {
        let path_str: String = Input::new()
            .with_prompt(format!("{} directory path (empty to finish)", label))
            .allow_empty(true)
            .interact_text()?;
        let path_str = path_str.trim().to_string();
        if path_str.is_empty() {
            break;
        }
        let p = Path::new(&path_str);
        if !p.is_dir() {
            println!(
                "  \x1b[0;31m✗\x1b[0m '{}' is not a directory, skipped",
                path_str
            );
            continue;
        }
        let name: String = Input::new()
            .with_prompt(format!("{} name", label))
            .with_initial_text(p.file_name().and_then(|n| n.to_str()).unwrap_or("unnamed"))
            .interact_text()?;
        let b64 = pack_dir(p)?;
        let size_kb = b64.len() * 3 / 4 / 1024;
        println!("  \x1b[0;32m✓\x1b[0m Packed '{}' ({} KB)", name, size_kb);
        items.push(serde_json::json!({ "name": name, "tar_gz_b64": b64 }));

        if !Confirm::new()
            .with_prompt(format!("Add another {}?", label))
            .default(false)
            .interact()?
        {
            break;
        }
    }
    Ok(items)
}
