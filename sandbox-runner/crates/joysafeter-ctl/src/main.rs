mod client;
mod commands;
mod manifest;
mod output;

use clap::{Parser, Subcommand};

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
        #[arg(long)]
        session: Option<String>,
        /// Agent name — creates a new session automatically
        #[arg(long)]
        agent: Option<String>,
        /// Polling interval in seconds
        #[arg(long, default_value = "2")]
        interval: u64,
    },
    /// Stream task output
    Logs {
        /// Task ID
        task: String,
        #[arg(short, long)]
        follow: bool,
        #[arg(long, default_value = "2")]
        interval: u64,
    },
    /// Full interactive setup: Secret → Environment → Agent → Session → Event
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
        id: String,
    },
    Events {
        #[arg(long)]
        session: String,
        #[arg(long)]
        limit: Option<i64>,
    },
    Tasks {
        #[arg(long)]
        agent: Option<String>,
    },
    Task {
        id: String,
    },
    Secrets,
    Secret {
        name: String,
    },
    MemoryStores,
    MemoryStore {
        id: String,
    },
    /// List memories in a memory store
    Memories {
        #[arg(long)]
        store: String,
    },
    /// Get a single memory
    Memory {
        #[arg(long)]
        store: String,
        id: String,
    },
    /// List memory versions for a store
    MemoryVersions {
        #[arg(long)]
        store: String,
    },
    Vaults,
    Vault {
        id: String,
    },
    VaultCredentials {
        #[arg(long)]
        vault: String,
    },
}

#[derive(Subcommand)]
enum CreateResource {
    /// Create a secret interactively
    Secret,
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
    /// Create a vault interactively
    Vault,
    /// Create a credential in a vault interactively
    VaultCredential,
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
        id: String,
    },
    Task {
        id: String,
    },
    Secret {
        name: String,
        #[arg(long)]
        force: bool,
    },
    MemoryStore {
        id: String,
    },
    /// Delete a memory from a store
    Memory {
        #[arg(long)]
        store: String,
        id: String,
    },
    Vault {
        id: String,
    },
    VaultCredential {
        #[arg(long)]
        vault: String,
        id: String,
    },
}

#[derive(Subcommand)]
enum EditResource {
    /// Edit an agent
    Agent { name: String },
    /// Edit an environment
    Environment { name: String },
    /// Edit a secret
    Secret { name: String },
    /// Edit a memory store
    MemoryStore { id: String },
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
            interval,
        } => commands::chat::run(&client, session, agent, interval).await?,
        Cmd::Logs {
            task,
            follow,
            interval,
        } => commands::logs::run(&client, &task, follow, interval).await?,
        Cmd::Delete { resource } => commands::delete::run(&client, &resource).await?,
        Cmd::Edit { resource } => commands::edit::run(&client, &resource).await?,
    }

    Ok(())
}
