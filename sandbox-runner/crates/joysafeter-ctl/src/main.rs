mod client;
mod commands;
mod editor;
mod manifest;
mod output;

use clap::{Parser, Subcommand};
use joysafeter_entity_id::{
    CredentialGroupId, CredentialId, MemoryId, MemoryStoreId, SessionId, TaskId,
};

#[derive(Parser)]
#[command(name = "joysafeterctl", about = "Declarative CLI for joysafeter")]
struct Cli {
    #[arg(long, env = "JOYSAFETER_URL", default_value = "http://localhost:8080")]
    server: String,

    #[arg(long, env = "JOYSAFETER_API_KEY")]
    api_key: Option<String>,

    #[arg(long, short, default_value = "table")]
    output: OutputFormat,

    #[command(subcommand)]
    command: Cmd,
}

#[derive(Clone, clap::ValueEnum)]
enum OutputFormat {
    Table,
    Json,
}

#[derive(Subcommand)]
enum Cmd {
    /// Show current authenticated user, organization, and project
    Whoami,
    /// Apply resources from YAML file(s)
    Apply {
        #[arg(short = 'f', long = "file")]
        file: String,
    },
    /// Get resources
    Get {
        #[command(subcommand)]
        resource: GetResource,
    },
    /// Interactively create a resource
    Create {
        #[command(subcommand)]
        resource: CreateResource,
    },
    /// Interactive chat with an agent session
    Chat {
        /// Session ID to resume
        #[arg(long, conflicts_with = "agent")]
        session: Option<SessionId>,
        /// Agent name — creates a new session automatically
        #[arg(long, conflicts_with = "session")]
        agent: Option<String>,
        /// Credential group to authorize for a new --agent session (repeatable)
        #[arg(long = "credential-group", requires = "agent")]
        credential_groups: Vec<CredentialGroupId>,
        /// Polling interval in seconds
        #[arg(long, default_value = "2")]
        interval: u64,
    },
    /// Stream task output
    Logs {
        /// Task ID
        task: TaskId,
        #[arg(short, long)]
        follow: bool,
        #[arg(long, default_value = "2")]
        interval: u64,
    },
    /// Full interactive setup with per-session MCP authorization
    Init,
    /// Delete resources
    Delete {
        #[command(subcommand)]
        resource: DeleteResource,
    },
    /// Edit a resource in $EDITOR (like kubectl edit)
    Edit {
        #[command(subcommand)]
        resource: EditResource,
    },
}

#[derive(Subcommand)]
enum GetResource {
    Agents,
    Agent {
        name: String,
    },
    Environments,
    Environment {
        name: String,
    },
    Sessions {
        #[arg(long)]
        agent: Option<String>,
        #[arg(long)]
        limit: Option<i64>,
    },
    Session {
        id: SessionId,
    },
    Events {
        #[arg(long)]
        session: SessionId,
        #[arg(long)]
        limit: Option<i64>,
    },
    Tasks {
        #[arg(long)]
        agent: Option<String>,
    },
    Task {
        id: TaskId,
    },
    Credentials,
    Credential {
        id: CredentialId,
    },
    MemoryStores,
    MemoryStore {
        id: MemoryStoreId,
    },
    /// List memories in a memory store
    Memories {
        #[arg(long)]
        store: MemoryStoreId,
    },
    /// Get a single memory
    Memory {
        #[arg(long)]
        store: MemoryStoreId,
        id: MemoryId,
    },
    /// List memory versions for a store
    MemoryVersions {
        #[arg(long)]
        store: MemoryStoreId,
    },
    CredentialGroups,
    CredentialGroup {
        id: CredentialGroupId,
    },
    CredentialGroupMembers {
        #[arg(long)]
        group: CredentialGroupId,
    },
}

#[derive(Subcommand)]
enum CreateResource {
    /// Create a credential interactively
    Credential,
    /// Create an environment interactively
    Environment,
    /// Create an agent interactively
    Agent,
    /// Create a session interactively
    Session,
    /// Send an event to a session interactively
    Event,
    /// Create a memory store interactively
    MemoryStore,
    /// Create a memory in a store interactively
    Memory,
    /// Create a credential group interactively
    CredentialGroup,
    /// Create a credential-group member interactively
    CredentialGroupMember,
}

#[derive(Subcommand)]
enum DeleteResource {
    Agent {
        name: String,
        #[arg(long)]
        force: bool,
    },
    Environment {
        name: String,
    },
    Session {
        id: SessionId,
    },
    Task {
        id: TaskId,
    },
    Credential {
        id: CredentialId,
    },
    MemoryStore {
        id: MemoryStoreId,
    },
    /// Delete a memory from a store
    Memory {
        #[arg(long)]
        store: MemoryStoreId,
        id: MemoryId,
    },
    CredentialGroup {
        id: CredentialGroupId,
    },
    CredentialGroupMember {
        #[arg(long)]
        group: CredentialGroupId,
        id: CredentialId,
    },
}

#[derive(Subcommand)]
enum EditResource {
    /// Edit an agent
    Agent { name: String },
    /// Edit an environment
    Environment { name: String },
    /// Edit a credential
    Credential { id: CredentialId },
    /// Edit a credential group
    CredentialGroup { id: CredentialGroupId },
    /// Edit a memory store
    MemoryStore { id: MemoryStoreId },
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let cli = Cli::parse();
    let client = client::JoysafeterClient::new(&cli.server, cli.api_key.clone());

    match cli.command {
        Cmd::Whoami => commands::auth::whoami(&client, &cli.output).await?,
        Cmd::Apply { file } => commands::apply::run(&client, &file).await?,
        Cmd::Get { resource } => commands::get::run(&client, &resource, &cli.output).await?,
        Cmd::Create { resource } => commands::create::run(&client, &resource).await?,
        Cmd::Init => commands::init::run(&client).await?,
        Cmd::Chat {
            session,
            agent,
            credential_groups,
            interval,
        } => commands::chat::run(&client, session, agent, &credential_groups, interval).await?,
        Cmd::Logs {
            task,
            follow,
            interval,
        } => commands::logs::run(&client, task, follow, interval).await?,
        Cmd::Delete { resource } => commands::delete::run(&client, &resource).await?,
        Cmd::Edit { resource } => commands::edit::run(&client, &resource).await?,
    }

    Ok(())
}

#[cfg(test)]
mod typed_id_cli_tests {
    use super::{Cli, Cmd};
    use clap::Parser;
    use joysafeter_entity_id::{
        CredentialGroupId, CredentialId, MemoryId, MemoryStoreId, SessionId, TaskId,
    };

    #[test]
    fn canonical_entity_ids_are_accepted() {
        let session_id = SessionId::new().to_string();
        let task_id = TaskId::new().to_string();
        let store_id = MemoryStoreId::new().to_string();
        let memory_id = MemoryId::new().to_string();
        let credential_id = CredentialId::new().to_string();
        let credential_group_id = CredentialGroupId::new().to_string();
        let cases = [
            vec!["joysafeterctl", "get", "session", session_id.as_str()],
            vec!["joysafeterctl", "logs", task_id.as_str()],
            vec![
                "joysafeterctl",
                "get",
                "memory",
                "--store",
                store_id.as_str(),
                memory_id.as_str(),
            ],
            vec!["joysafeterctl", "get", "credential", credential_id.as_str()],
            vec![
                "joysafeterctl",
                "get",
                "credential-group",
                credential_group_id.as_str(),
            ],
            vec![
                "joysafeterctl",
                "get",
                "credential-group-members",
                "--group",
                credential_group_id.as_str(),
            ],
        ];

        for args in cases {
            assert!(Cli::try_parse_from(args).is_ok());
        }
    }

    #[test]
    fn bare_uuids_are_rejected_for_entity_id_arguments() {
        let raw = SessionId::new().as_uuid().to_string();
        for args in [
            vec!["joysafeterctl", "get", "session", raw.as_str()],
            vec!["joysafeterctl", "logs", raw.as_str()],
            vec!["joysafeterctl", "get", "memory-store", raw.as_str()],
        ] {
            assert!(Cli::try_parse_from(args).is_err());
        }
    }

    #[test]
    fn cross_entity_ids_are_rejected_for_credential_arguments() {
        let credential_id = CredentialId::new().to_string();
        let credential_group_id = CredentialGroupId::new().to_string();

        assert!(Cli::try_parse_from([
            "joysafeterctl",
            "get",
            "credential",
            credential_group_id.as_str(),
        ])
        .is_err());
        assert!(Cli::try_parse_from([
            "joysafeterctl",
            "get",
            "credential-group",
            credential_id.as_str(),
        ])
        .is_err());
    }

    #[test]
    fn chat_accepts_repeatable_credential_groups_for_new_sessions() {
        let first_group_id = CredentialGroupId::new().to_string();
        let second_group_id = CredentialGroupId::new().to_string();
        let cli = Cli::try_parse_from([
            "joysafeterctl",
            "chat",
            "--agent",
            "researcher",
            "--credential-group",
            first_group_id.as_str(),
            "--credential-group",
            second_group_id.as_str(),
        ])
        .unwrap();

        let Cmd::Chat {
            credential_groups, ..
        } = cli.command
        else {
            panic!("expected chat command");
        };
        assert_eq!(credential_groups.len(), 2);
    }

    #[test]
    fn chat_rejects_credential_groups_without_agent() {
        let group_id = CredentialGroupId::new().to_string();
        assert!(Cli::try_parse_from([
            "joysafeterctl",
            "chat",
            "--credential-group",
            group_id.as_str(),
        ])
        .is_err());
    }

    #[test]
    fn chat_rejects_session_and_agent_together() {
        let session_id = SessionId::new().to_string();
        assert!(Cli::try_parse_from([
            "joysafeterctl",
            "chat",
            "--session",
            session_id.as_str(),
            "--agent",
            "researcher",
        ])
        .is_err());
    }
}
