use crate::client::JoysafeterClient;
use anyhow::{bail, Context};
use dialoguer::{Input, Select};
use rustyline::DefaultEditor;
use std::collections::HashSet;
use std::time::Duration;

pub async fn run(
    client: &JoysafeterClient,
    session_arg: Option<String>,
    agent_arg: Option<String>,
    interval: u64,
) -> anyhow::Result<()> {
    let session_id = resolve_session(client, session_arg, agent_arg).await?;

    println!();
    println!(
        "\x1b[1;36mjoysafeterctl chat\x1b[0m — session {}",
        session_id
    );
    println!("Type a message and press Enter. /quit to exit, /help for commands.");
    println!();

    let (mut seen_ids, mut last_seq) = collect_event_ids(client, &session_id).await;
    let mut rl = DefaultEditor::new()?;

    loop {
        let readline = rl.readline("\x1b[1;32myou>\x1b[0m ");
        let input = match readline {
            Ok(line) => line,
            Err(
                rustyline::error::ReadlineError::Interrupted | rustyline::error::ReadlineError::Eof,
            ) => break,
            Err(e) => return Err(e.into()),
        };
        let input = input.trim();
        if input.is_empty() {
            continue;
        }
        rl.add_history_entry(input)?;

        match input {
            "/quit" | "/exit" | "/q" => break,
            "/help" | "/h" => {
                print_help();
                continue;
            }
            cmd if cmd.starts_with("/events") => {
                let n = cmd
                    .strip_prefix("/events")
                    .and_then(|s| s.trim().parse::<i64>().ok())
                    .unwrap_or(20);
                show_events(client, &session_id, n).await?;
                continue;
            }
            "/status" | "/s" => {
                show_status(client, &session_id).await?;
                continue;
            }
            _ => {}
        }

        let body = serde_json::json!({
            "type": "user.message",
            "content": [{"type": "text", "text": input}],
        });
        client.send_event(&session_id, &body).await?;

        poll_until_idle(client, &session_id, interval, &mut seen_ids, &mut last_seq).await?;
    }

    println!("\nBye.");
    Ok(())
}

async fn resolve_session(
    client: &JoysafeterClient,
    session_arg: Option<String>,
    agent_arg: Option<String>,
) -> anyhow::Result<String> {
    if let Some(sid) = session_arg {
        client
            .get_session(&sid)
            .await
            .context("Session not found")?;
        return Ok(sid);
    }

    if let Some(agent_name) = agent_arg {
        let agent = client
            .get_agent_by_name(&agent_name)
            .await?
            .ok_or_else(|| anyhow::anyhow!("Agent '{}' not found", agent_name))?;
        let agent_id = agent["id"].as_str().unwrap();
        let env_ref = agent.get("environment_ref").and_then(|v| v.as_str());

        let mut body = serde_json::json!({ "agent_id": agent_id });
        if let Some(env_name) = env_ref {
            if let Some(env) = client.get_environment_by_name(env_name).await? {
                if let Some(eid) = env["id"].as_str() {
                    body["environment_id"] = serde_json::Value::String(eid.to_string());
                }
            }
        }
        let resp = client.create_session(&body).await?;
        let sid = resp["id"].as_str().unwrap().to_string();
        println!("Created new session: {}", sid);
        return Ok(sid);
    }

    let all_sessions = client.list_sessions(Some(100), None).await?;
    if all_sessions.is_empty() {
        bail!("No sessions found. Use --agent <name> to create one, or create a session first.");
    }

    let keyword: String = Input::new()
        .with_prompt("Search sessions (empty to list all)")
        .allow_empty(true)
        .interact_text()?;
    let keyword = keyword.trim().to_lowercase();

    let filtered: Vec<&serde_json::Value> = if keyword.is_empty() {
        all_sessions.iter().collect()
    } else {
        all_sessions
            .iter()
            .filter(|s| {
                let id = s["id"].as_str().unwrap_or("");
                let title = s["title"].as_str().unwrap_or("");
                let status = s["status"].as_str().unwrap_or("");
                let agent = s["agent"]
                    .as_str()
                    .or_else(|| s["agent_id"].as_str())
                    .unwrap_or("");
                id.to_lowercase().contains(&keyword)
                    || title.to_lowercase().contains(&keyword)
                    || status.to_lowercase().contains(&keyword)
                    || agent.to_lowercase().contains(&keyword)
            })
            .collect()
    };

    if filtered.is_empty() {
        bail!("No sessions matching '{}'", keyword);
    }

    let labels: Vec<String> = filtered
        .iter()
        .map(|s| {
            let id = s["id"].as_str().unwrap_or("?");
            let title = s["title"].as_str().unwrap_or("untitled");
            let status = s["status"].as_str().unwrap_or("?");
            format!("{} ({}) [{}]", id, title, status)
        })
        .collect();
    let idx = Select::new()
        .with_prompt("Select session")
        .items(&labels)
        .default(0)
        .interact()?;
    Ok(filtered[idx]["id"].as_str().unwrap().to_string())
}

async fn collect_event_ids(client: &JoysafeterClient, session_id: &str) -> (HashSet<String>, i64) {
    let events = client
        .list_events(session_id, Some(1000))
        .await
        .unwrap_or_default();
    let mut max_seq: i64 = 0;
    let ids = events
        .iter()
        .filter_map(|e| {
            if let Some(seq) = e["seq"].as_i64() {
                if seq > max_seq {
                    max_seq = seq;
                }
            }
            e["id"].as_str().map(String::from)
        })
        .collect();
    (ids, max_seq)
}

async fn poll_until_idle(
    client: &JoysafeterClient,
    session_id: &str,
    interval: u64,
    seen_ids: &mut HashSet<String>,
    last_seq: &mut i64,
) -> anyhow::Result<()> {
    let mut printed_running = false;

    loop {
        tokio::time::sleep(Duration::from_secs(interval)).await;

        let after_seq = if *last_seq > 0 { Some(*last_seq) } else { None };
        let events = client
            .list_events_after(session_id, Some(200), after_seq)
            .await?;
        render_new_events(&events, seen_ids, &mut printed_running);
        for e in &events {
            if let Some(seq) = e["seq"].as_i64() {
                if seq > *last_seq {
                    *last_seq = seq;
                }
            }
        }

        let session = client.get_session(session_id).await?;
        let status = session["status"].as_str().unwrap_or("");

        if status != "idle" {
            continue;
        }

        let stop_type = session
            .get("stop_reason")
            .and_then(|sr| sr["type"].as_str())
            .unwrap_or("");

        match stop_type {
            "end_turn" => return Ok(()),
            "requires_action" => {
                let event_ids: Vec<String> = session
                    .get("stop_reason")
                    .and_then(|sr| sr["event_ids"].as_array())
                    .map(|arr| {
                        arr.iter()
                            .filter_map(|v| v.as_str().map(String::from))
                            .collect()
                    })
                    .unwrap_or_default();

                for eid in &event_ids {
                    let evt = events.iter().find(|e| e["id"].as_str() == Some(eid));
                    let etype = evt.and_then(|e| e["type"].as_str()).unwrap_or("");

                    if etype == "agent.custom_tool_use" {
                        handle_custom_tool(client, session_id, eid, evt).await?;
                    } else {
                        handle_tool_approval(client, session_id, eid, evt).await?;
                    }
                }
                printed_running = false;
            }
            _ => return Ok(()),
        }
    }
}

fn render_new_events(
    events: &[serde_json::Value],
    seen_ids: &mut HashSet<String>,
    printed_running: &mut bool,
) {
    for e in events {
        let id = match e["id"].as_str() {
            Some(id) => id,
            None => continue,
        };
        if seen_ids.contains(id) {
            continue;
        }
        seen_ids.insert(id.to_string());

        let etype = e["type"].as_str().unwrap_or("");
        match etype {
            "agent.message" => {
                let text = extract_content_text(e);
                if !text.is_empty() {
                    println!("\n\x1b[1;35magent>\x1b[0m {}", text);
                }
            }
            "agent.tool_use" => {
                let name = e["name"].as_str().unwrap_or("?");
                let input_preview = e["input"]
                    .as_str()
                    .unwrap_or("")
                    .chars()
                    .take(80)
                    .collect::<String>();
                println!("  \x1b[33m[tool]\x1b[0m {}: {}", name, input_preview);
            }
            "agent.tool_result" => {
                let output = e["output"]
                    .as_str()
                    .unwrap_or("")
                    .chars()
                    .take(120)
                    .collect::<String>();
                if !output.is_empty() {
                    println!("  \x1b[90m[result]\x1b[0m {}", output);
                }
            }
            "agent.custom_tool_use" => {
                let name = e["name"].as_str().unwrap_or("?");
                let input_str = e["input"]
                    .as_str()
                    .unwrap_or("")
                    .chars()
                    .take(80)
                    .collect::<String>();
                println!("  \x1b[33m[custom tool]\x1b[0m {}: {}", name, input_str);
            }
            "session.status_running" => {
                if !*printed_running {
                    println!("  \x1b[90m[agent running...]\x1b[0m");
                    *printed_running = true;
                }
            }
            _ => {}
        }
    }
}

fn extract_content_text(event: &serde_json::Value) -> String {
    if let Some(arr) = event["content"].as_array() {
        arr.iter()
            .filter_map(|b| b["text"].as_str())
            .collect::<Vec<_>>()
            .join("")
    } else {
        event["content"].as_str().unwrap_or("").to_string()
    }
}

async fn handle_tool_approval(
    client: &JoysafeterClient,
    session_id: &str,
    event_id: &str,
    event: Option<&serde_json::Value>,
) -> anyhow::Result<()> {
    let name = event.and_then(|e| e["name"].as_str()).unwrap_or("?");
    let input_str = event
        .and_then(|e| e["input"].as_str())
        .unwrap_or("")
        .chars()
        .take(200)
        .collect::<String>();

    println!();
    println!(
        "  \x1b[1;33m[approval required]\x1b[0m {}: {}",
        name, input_str
    );

    let choices = vec!["approve (a)", "deny (d)"];
    let idx = Select::new()
        .with_prompt("Action")
        .items(&choices)
        .default(0)
        .interact()?;

    let body = if idx == 0 {
        serde_json::json!({
            "type": "user.tool_confirmation",
            "tool_use_id": event_id,
            "result": "allow",
        })
    } else {
        let reason: String = Input::new()
            .with_prompt("Deny reason (optional)")
            .allow_empty(true)
            .interact_text()?;
        let mut v = serde_json::json!({
            "type": "user.tool_confirmation",
            "tool_use_id": event_id,
            "result": "deny",
        });
        if !reason.trim().is_empty() {
            v["deny_message"] = serde_json::Value::String(reason.trim().to_string());
        }
        v
    };

    client.send_event(session_id, &body).await?;
    Ok(())
}

async fn handle_custom_tool(
    client: &JoysafeterClient,
    session_id: &str,
    event_id: &str,
    event: Option<&serde_json::Value>,
) -> anyhow::Result<()> {
    let name = event.and_then(|e| e["name"].as_str()).unwrap_or("?");
    let input_str = event
        .and_then(|e| e["input"].as_str())
        .unwrap_or("")
        .chars()
        .take(200)
        .collect::<String>();

    println!();
    println!(
        "  \x1b[1;33m[custom tool call]\x1b[0m {}: {}",
        name, input_str
    );

    let result: String = Input::new().with_prompt("Tool result").interact_text()?;

    let body = serde_json::json!({
        "type": "user.custom_tool_result",
        "tool_use_event_id": event_id,
        "content": result,
    });

    client.send_event(session_id, &body).await?;
    Ok(())
}

async fn show_events(
    client: &JoysafeterClient,
    session_id: &str,
    limit: i64,
) -> anyhow::Result<()> {
    let events = client.list_events(session_id, Some(limit)).await?;
    for (i, e) in events.iter().enumerate() {
        let etype = e["type"].as_str().unwrap_or("?");
        let snippet = match etype {
            "user.message" | "agent.message" => {
                let text = extract_content_text(e);
                let chars: Vec<char> = text.chars().collect();
                if chars.len() > 200 {
                    format!("{}…", chars[..200].iter().collect::<String>())
                } else {
                    text
                }
            }
            t if t.contains("tool_use") => {
                format!(
                    "{}({})",
                    e["name"].as_str().unwrap_or("?"),
                    e["input"]
                        .as_str()
                        .unwrap_or("")
                        .chars()
                        .take(80)
                        .collect::<String>()
                )
            }
            _ => String::new(),
        };
        let snippet = snippet.replace('\n', " ↵ ");
        println!("  {:>4}  {:<28} {}", i + 1, etype, snippet);
    }
    Ok(())
}

async fn show_status(client: &JoysafeterClient, session_id: &str) -> anyhow::Result<()> {
    let session = client.get_session(session_id).await?;
    println!("  ID:      {}", session["id"].as_str().unwrap_or("-"));
    println!("  Status:  {}", session["status"].as_str().unwrap_or("-"));
    if let Some(sr) = session.get("stop_reason") {
        if !sr.is_null() {
            println!("  Stop:    {}", sr["type"].as_str().unwrap_or("-"));
        }
    }
    if let Some(usage) = session.get("usage") {
        if !usage.is_null() {
            let input = usage["input_tokens"].as_i64().unwrap_or(0);
            let output = usage["output_tokens"].as_i64().unwrap_or(0);
            println!("  Tokens:  {} in / {} out", input, output);
        }
    }
    Ok(())
}

fn print_help() {
    println!("  /quit, /exit, /q   Exit chat");
    println!("  /events [n]        Show recent events (default: 20)");
    println!("  /status, /s        Show session status and token usage");
    println!("  /help, /h          Show this help");
}
