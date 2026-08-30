use joysafeter_runtime::claude_project_config::prepare_claude_project_config;
use joysafeter_types::agent::McpServerConfig;
use joysafeter_types::harness::CustomToolDefinition;
use joysafeter_types::tool_policy::{ToolDecision, ToolPolicy, ToolRule};

#[tokio::test]
async fn project_config_replaces_stale_runtime_owned_state() {
    let dir = tempfile::tempdir().unwrap();
    tokio::fs::create_dir_all(dir.path().join(".claude"))
        .await
        .unwrap();
    tokio::fs::write(
        dir.path().join(".mcp.json"),
        r#"{"mcpServers":{"stale":{"type":"http","url":"https://stale"}}}"#,
    )
    .await
    .unwrap();
    tokio::fs::write(
        dir.path().join(".claude/settings.json"),
        r#"{"permissions":{"allow":["stale"]},"unowned":true}"#,
    )
    .await
    .unwrap();

    let policy = ToolPolicy::new(
        ToolDecision::Allow,
        vec![
            ToolRule::mcp_server("docs", ToolDecision::Ask).unwrap(),
            ToolRule::builtin("Write", ToolDecision::Deny).unwrap(),
        ],
    )
    .unwrap();
    prepare_claude_project_config(
        dir.path(),
        &[McpServerConfig::StreamableHttp {
            name: "docs".into(),
            url: "https://docs.example/mcp".into(),
        }],
        &[CustomToolDefinition {
            name: "lookup".into(),
            description: "Lookup a record".into(),
            input_schema: serde_json::json!({"type": "object"}),
        }],
        &policy,
    )
    .await
    .unwrap();

    let mcp: serde_json::Value =
        serde_json::from_slice(&tokio::fs::read(dir.path().join(".mcp.json")).await.unwrap())
            .unwrap();
    assert!(mcp.pointer("/mcpServers/docs").is_some());
    assert!(mcp.pointer("/mcpServers/stale").is_none());

    let settings: serde_json::Value = serde_json::from_slice(
        &tokio::fs::read(dir.path().join(".claude/settings.json"))
            .await
            .unwrap(),
    )
    .unwrap();
    assert_eq!(
        settings["permissions"]["ask"],
        serde_json::json!(["mcp__docs__*"])
    );
    assert_eq!(
        settings["permissions"]["deny"],
        serde_json::json!(["Write"])
    );
    assert_eq!(settings["customTools"][0]["name"], "lookup");
    assert!(settings.get("unowned").is_none());
}

#[tokio::test]
async fn empty_input_clears_previous_project_capabilities() {
    let dir = tempfile::tempdir().unwrap();
    tokio::fs::create_dir_all(dir.path().join(".claude"))
        .await
        .unwrap();
    tokio::fs::write(dir.path().join(".mcp.json"), b"stale")
        .await
        .unwrap();
    tokio::fs::write(dir.path().join(".claude/settings.json"), b"stale")
        .await
        .unwrap();

    let policy = ToolPolicy::new(ToolDecision::Allow, vec![]).unwrap();
    prepare_claude_project_config(dir.path(), &[], &[], &policy)
        .await
        .unwrap();

    let mcp: serde_json::Value =
        serde_json::from_slice(&tokio::fs::read(dir.path().join(".mcp.json")).await.unwrap())
            .unwrap();
    let settings: serde_json::Value = serde_json::from_slice(
        &tokio::fs::read(dir.path().join(".claude/settings.json"))
            .await
            .unwrap(),
    )
    .unwrap();
    assert_eq!(mcp, serde_json::json!({"mcpServers": {}}));
    assert_eq!(settings, serde_json::json!({}));
}
