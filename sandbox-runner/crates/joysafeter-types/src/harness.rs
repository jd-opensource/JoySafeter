use async_trait::async_trait;
use serde::{Deserialize, Serialize};
use std::any::Any;
use std::collections::HashMap;
use std::path::Path;
use std::time::Duration;
use thiserror::Error;
use tokio::process::Child;
use tokio::sync::{mpsc, oneshot};

use crate::token_usage::TokenUsage;

#[derive(Debug, Error)]
pub enum HarnessError {
    #[error("failed to start agent CLI: {0}")]
    StartFailed(String),
    #[error("CLI not found: {0}")]
    CliNotFound(String),
    #[error("failed to cancel agent: {0}")]
    CancelFailed(String),
    #[error("stream parse error: {0}")]
    ParseError(String),
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
    #[error("send input is not supported by this adapter")]
    UnsupportedInput,
}

#[derive(Debug, Clone)]
pub struct HarnessInput {
    pub prompt: String,
    pub system_prompt: Option<String>,
    pub session_id: Option<String>,
    pub model: Option<String>,
    pub max_turns: Option<u32>,
    pub timeout: Duration,
    pub env: HashMap<String, String>,
    pub secrets: HashMap<String, String>,
    pub mcp_configs: Vec<crate::agent::McpServerConfig>,
    pub permission_mode: String,
    /// Tool permission rules (Claude Code settings.json permissions).
    /// Official Managed Agents model: allow + ask only (no deny).
    /// allowed -> permissions.allow, ask -> permissions.ask.
    pub allowed_tools: Vec<String>,
    pub ask_tools: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum HarnessEvent {
    Text {
        content: String,
    },
    Thinking {
        content: String,
    },
    ToolUse {
        tool: String,
        call_id: String,
        input: serde_json::Value,
        #[serde(default)]
        is_control_request: bool,
    },
    ToolResult {
        tool: String,
        call_id: String,
        output: String,
    },
    Error {
        message: String,
    },
    Status {
        state: String,
    },
    Log {
        level: String,
        message: String,
    },
    ModelRequestStart {
        model: String,
    },
    ModelRequestEnd {
        model: String,
        input_tokens: u64,
        output_tokens: u64,
        cache_read_tokens: u64,
        cache_write_tokens: u64,
    },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HarnessResult {
    pub status: HarnessResultStatus,
    pub output: String,
    pub error: Option<String>,
    pub session_id: Option<String>,
    pub usage: TokenUsage,
    pub duration: Duration,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum HarnessResultStatus {
    Completed,
    Failed,
    Aborted,
    Timeout,
}

impl std::fmt::Display for HarnessResultStatus {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Completed => write!(f, "completed"),
            Self::Failed => write!(f, "failed"),
            Self::Aborted => write!(f, "aborted"),
            Self::Timeout => write!(f, "timeout"),
        }
    }
}

pub struct RunningHarness {
    pub events: mpsc::Receiver<HarnessEvent>,
    pub result: oneshot::Receiver<HarnessResult>,
    pub child: Option<Child>,
    pub input: Option<Box<dyn Any + Send + Sync>>,
}

#[async_trait]
pub trait HarnessAdapter: Send + Sync {
    async fn start(&self, input: HarnessInput, cwd: &Path) -> Result<RunningHarness, HarnessError>;

    async fn cancel(&self, harness: &mut RunningHarness) -> Result<(), HarnessError>;

    async fn send_input(
        &self,
        _harness: &mut RunningHarness,
        _content: String,
    ) -> Result<(), HarnessError> {
        Err(HarnessError::UnsupportedInput)
    }

    fn provider(&self) -> &str;

    async fn is_available(&self) -> bool;
}
