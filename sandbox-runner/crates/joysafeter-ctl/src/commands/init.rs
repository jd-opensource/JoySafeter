use crate::client::JoysafeterClient;
use anyhow::{bail, Context};
use base64::Engine as _;
use dialoguer::{Confirm, Input, Select};
use std::path::Path;

enum StepResult {
    UsedExisting,
    Created { id: String, name: String },
    Skipped,
}

impl Default for StepResult {
    fn default() -> Self {
        Self::Skipped
    }
}

#[derive(Default)]
struct WizardState {
    secret_name: String,
    secret_result: StepResult,

    env_name: String,
    env_id: String,
    env_result: StepResult,

    agent_id: String,
    agent_result: StepResult,

    memory_store_resources: Vec<serde_json::Value>,
    memory_store_id: Option<String>,
    memory_store_result: StepResult,

    session_id: String,
    session_result: StepResult,
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
    println!("║    1. Secret       (API credentials)             ║");
    println!("║    2. Environment  (sandbox config)              ║");
    println!("║    3. Agent        (model + tools)               ║");
    println!("║    4. Memory Store (persistent memory, optional) ║");
    println!("║    5. Session      (conversation)                ║");
    println!("║    6. Event        (first message)               ║");
    println!("╚═══════════════════════════════════════════════════╝");
    println!();

    let mut step: usize = 1;
    let mut state = WizardState::default();

    loop {
        let action = match step {
            1 => run_step_secret(client, &mut state, true).await?,
            2 => run_step_environment(client, &mut state, true).await?,
            3 => run_step_agent(client, &mut state, true).await?,
            4 => run_step_memory_store(client, &mut state, true).await?,
            5 => run_step_session(client, &mut state, true).await?,
            6 => {
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
    if !state.secret_name.is_empty() {
        println!("║  Secret:      {:<36} ║", state.secret_name);
    }
    println!("║  Environment: {:<36} ║", state.env_name);
    println!("║  Agent ID:    {:<36} ║", state.agent_id);
    println!("║  Session ID:  {:<36} ║", state.session_id);
    println!("╚═══════════════════════════════════════════════════╝");

    // ── Enter chat mode ────────────────────────────────
    println!();
    println!("Entering chat mode...");
    super::chat::run(client, Some(state.session_id), None, 2).await
}

async fn rollback_step(
    client: &JoysafeterClient,
    step: usize,
    state: &mut WizardState,
) -> anyhow::Result<()> {
    match step {
        1 => {
            if let StepResult::Created { ref id, ref name } = state.secret_result {
                println!("  \u{21a9} Deleting secret/{} ...", name);
                client.delete_secret(id, true).await.ok();
            }
            state.secret_name.clear();
            state.secret_result = StepResult::Skipped;
        }
        2 => {
            if let StepResult::Created { ref id, ref name } = state.env_result {
                println!("  \u{21a9} Deleting environment/{} ...", name);
                client.delete_environment(id).await.ok();
            }
            state.env_name.clear();
            state.env_id.clear();
            state.env_result = StepResult::Skipped;
        }
        3 => {
            if let StepResult::Created { ref id, .. } = state.agent_result {
                println!("  \u{21a9} Deleting agent/{} ...", id);
                client.delete_agent(id, true).await.ok();
            }
            state.agent_id.clear();
            state.agent_result = StepResult::Skipped;
        }
        4 => {
            if let StepResult::Created { ref id, ref name } = state.memory_store_result {
                println!("  \u{21a9} Deleting memorystore/{} ...", name);
                client.delete_memory_store(id).await.ok();
            }
            state.memory_store_resources.clear();
            state.memory_store_id = None;
            state.memory_store_result = StepResult::Skipped;
        }
        5 => {
            if let StepResult::Created { ref id, .. } = state.session_result {
                println!("  \u{21a9} Deleting session/{} ...", id);
                client.delete_session(id).await.ok();
            }
            state.session_id.clear();
            state.session_result = StepResult::Skipped;
        }
        _ => {}
    }
    Ok(())
}

// ── Step 1: Secret ──────────────────────────────────────────────

async fn run_step_secret(
    client: &JoysafeterClient,
    state: &mut WizardState,
    allow_back: bool,
) -> anyhow::Result<StepAction> {
    println!("\x1b[1;36m━━━ Step 1/6: Secret ━━━\x1b[0m\n");

    let existing = client.list_secrets().await.unwrap_or_default();
    let choice = pick_or_create("secret", &existing, "name", allow_back, true)?;
    match choice {
        PickResult::Existing(name) => {
            println!("  Using existing secret: {}", name);
            state.secret_name = name;
            state.secret_result = StepResult::UsedExisting;
        }
        PickResult::Create => {
            let name = input_required("Secret name")?;
            let mut data = serde_json::Map::new();

            let providers = vec![
                "Claude (Anthropic)",
                "Codex (OpenAI)",
                "Custom (manual key-value pairs)",
            ];
            let provider_idx = Select::new()
                .with_prompt("Provider")
                .items(&providers)
                .default(0)
                .interact()?;

            match provider_idx {
                0 => {
                    let auth_types = vec![
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
                        .with_prompt("CODEX_BASE_URL (API base URL, empty for default: https://code.ppchat.vip/v1)")
                        .allow_empty(true)
                        .interact_text()?;
                    if !base_url.trim().is_empty() {
                        data.insert(
                            "CODEX_BASE_URL".to_string(),
                            serde_json::Value::String(base_url.trim().to_string()),
                        );
                    }
                    let model: String = Input::new()
                        .with_prompt("CODEX_MODEL (empty for default: gpt-5.3-codex)")
                        .allow_empty(true)
                        .interact_text()?;
                    if !model.trim().is_empty() {
                        data.insert(
                            "CODEX_MODEL".to_string(),
                            serde_json::Value::String(model.trim().to_string()),
                        );
                    }
                    let effort: String = Input::new()
                        .with_prompt("CODEX_REASONING_EFFORT (empty for default: high)")
                        .allow_empty(true)
                        .interact_text()?;
                    if !effort.trim().is_empty() {
                        data.insert(
                            "CODEX_REASONING_EFFORT".to_string(),
                            serde_json::Value::String(effort.trim().to_string()),
                        );
                    }
                }
                _ => {}
            }

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
                bail!("Secret must have at least one key-value pair");
            }
            let body = serde_json::json!({ "name": name, "data": serde_json::Value::Object(data) });
            let resp = client.create_secret(&body).await?;
            let id = resp["id"].as_str().unwrap_or("").to_string();
            println!("  \x1b[0;32m✓\x1b[0m secret/{} created", name);
            state.secret_name = name.clone();
            state.secret_result = StepResult::Created { id, name };
        }
        PickResult::Skip => {
            println!("  Skipped.");
            state.secret_name.clear();
            state.secret_result = StepResult::Skipped;
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
    println!("\n\x1b[1;36m━━━ Step 2/6: Environment ━━━\x1b[0m\n");

    let existing = client.list_environments().await.unwrap_or_default();
    let choice = pick_or_create("environment", &existing, "name", allow_back, true)?;
    match choice {
        PickResult::Back => return Ok(StepAction::Back),
        PickResult::Existing(name) => {
            let envs = client.list_environments().await?;
            let found = envs.iter().find(|e| e["name"].as_str() == Some(&name));
            state.env_id = found
                .and_then(|e| e["id"].as_str())
                .map(normalize_resource_id)
                .unwrap_or_default();
            state.env_name = name;
            state.env_result = StepResult::UsedExisting;
            println!("  Using existing environment: {}", state.env_name);
        }
        PickResult::Create => {
            let name = input_required("Environment name")?;
            let net_types = vec!["unrestricted", "limited"];
            let net_idx = Select::new()
                .with_prompt("Networking type")
                .items(&net_types)
                .default(0)
                .interact()?;
            let net_type = net_types[net_idx];

            let mut allowed_hosts: Vec<String> = Vec::new();
            if net_type == "limited" {
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

            let mut networking = serde_json::json!({"type": net_type});
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
                .map(normalize_resource_id)
                .unwrap_or_default();
            println!("  \x1b[0;32m✓\x1b[0m environment/{} created", name);
            state.env_id = id.clone();
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
    println!("\n\x1b[1;36m━━━ Step 3/6: Agent ━━━\x1b[0m\n");

    let existing = client.list_agents().await.unwrap_or_default();
    let choice = pick_or_create("agent", &existing, "name", allow_back, true)?;
    match choice {
        PickResult::Back => return Ok(StepAction::Back),
        PickResult::Existing(name) => {
            let agents = client.list_agents().await?;
            let found = agents.iter().find(|a| a["name"].as_str() == Some(&name));
            state.agent_id = found
                .and_then(|a| a["id"].as_str())
                .map(normalize_resource_id)
                .unwrap_or_default();
            state.agent_result = StepResult::UsedExisting;
            println!("  Using existing agent: {} ({})", name, state.agent_id);
        }
        PickResult::Create => {
            let name = input_required("Agent name")?;
            let engines = vec!["claude", "codex"];
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
            if !state.secret_name.is_empty() {
                body["secret_ref"] = serde_json::Value::String(state.secret_name.clone());
                println!("  Auto-linking secret: {}", state.secret_name);
            }
            if !state.env_name.is_empty() {
                body["environment_ref"] = serde_json::Value::String(state.env_name.clone());
                println!("  Auto-linking environment: {}", state.env_name);
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
                .map(normalize_resource_id)
                .unwrap_or_default();
            println!("  \x1b[0;32m✓\x1b[0m agent/{} created ({})", name, id);
            state.agent_id = id.clone();
            state.agent_result = StepResult::Created { id, name };
        }
        PickResult::Skip => {
            state.agent_result = StepResult::Skipped;
            println!("  Skipped");
        }
    }
    Ok(StepAction::Completed)
}

// ── Step 4: Memory Store ────────────────────────────────────────

async fn run_step_memory_store(
    client: &JoysafeterClient,
    state: &mut WizardState,
    allow_back: bool,
) -> anyhow::Result<StepAction> {
    println!("\n\x1b[1;36m━━━ Step 4/6: Memory Store (optional) ━━━\x1b[0m\n");

    let existing = client.list_memory_stores().await.unwrap_or_default();
    let choice = pick_or_create("memory store", &existing, "name", allow_back, true)?;
    match choice {
        PickResult::Back => return Ok(StepAction::Back),
        PickResult::Existing(name) => {
            let stores = client.list_memory_stores().await?;
            let found = stores.iter().find(|s| s["name"].as_str() == Some(&name));
            if let Some(store) = found {
                let store_id = store["id"]
                    .as_str()
                    .map(normalize_resource_id)
                    .unwrap_or_default();
                let access_opts = vec!["read_write", "read_only"];
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
                .map(normalize_resource_id)
                .unwrap_or_default();
            println!("  \x1b[0;32m✓\x1b[0m memorystore/{} created", name);
            state.memory_store_resources = vec![serde_json::json!({
                "type": "memory_store",
                "memory_store_id": id,
                "access": "read_write",
            })];
            state.memory_store_id = Some(id.clone());
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

// ── Step 5: Session ─────────────────────────────────────────────

async fn run_step_session(
    client: &JoysafeterClient,
    state: &mut WizardState,
    allow_back: bool,
) -> anyhow::Result<StepAction> {
    println!("\n\x1b[1;36m━━━ Step 5/6: Session ━━━\x1b[0m\n");

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

    let mut session_body = serde_json::json!({
        "agent_id": state.agent_id,
        "environment_id": state.env_id,
    });
    if let Some(t) = &title {
        session_body["title"] = serde_json::Value::String(t.clone());
    }
    if !state.memory_store_resources.is_empty() {
        session_body["resources"] = serde_json::json!(state.memory_store_resources);
    }

    let resp = client.create_session(&session_body).await?;
    let id = resp["id"].as_str().unwrap_or("?").to_string();
    println!("  \x1b[0;32m✓\x1b[0m session/{} created", id);
    state.session_id = id.clone();
    state.session_result = StepResult::Created {
        id,
        name: String::new(),
    };
    Ok(StepAction::Completed)
}

// ── Step 6: First Event ─────────────────────────────────────────

async fn run_step_event(
    client: &JoysafeterClient,
    state: &mut WizardState,
    allow_back: bool,
) -> anyhow::Result<StepAction> {
    println!("\n\x1b[1;36m━━━ Step 6/6: Send First Message ━━━\x1b[0m\n");

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
        client.send_event(&state.session_id, &event_body).await?;
        println!(
            "  \x1b[0;32m✓\x1b[0m event sent to session/{}",
            state.session_id
        );
    } else {
        println!("  Skipped. You can send events later:");
        println!("    joysafeterctl create event");
    }
    Ok(StepAction::Completed)
}

// ── Helpers ─────────────────────────────────────────────────────

enum PickResult {
    Existing(String),
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
            options.push(format!("Skip (not required)"));
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

    let default_idx = if skippable { 0 } else { 0 };
    let idx = Select::new()
        .with_prompt(format!("Select or create {}", resource))
        .items(&labels)
        .default(default_idx)
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
        let name = existing[idx - existing_offset][name_field]
            .as_str()
            .unwrap_or("?")
            .to_string();
        Ok(PickResult::Existing(name))
    }
}

fn input_required(prompt: &str) -> anyhow::Result<String> {
    let val: String = Input::new().with_prompt(prompt).interact_text()?;
    if val.trim().is_empty() {
        bail!("{} cannot be empty", prompt);
    }
    Ok(val.trim().to_string())
}

fn normalize_resource_id(id: &str) -> String {
    id.split_once('_')
        .map(|(_, rest)| rest)
        .unwrap_or(id)
        .to_string()
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
