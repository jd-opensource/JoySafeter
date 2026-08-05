use serde::{Deserialize, Serialize, Serializer};
use std::collections::HashMap;
use std::fmt;

fn serialize_environment_id<S: Serializer>(id: &uuid::Uuid, s: S) -> Result<S::Ok, S::Error> {
    s.serialize_str(&format!("env_{id}"))
}

pub fn parse_environment_id(s: &str) -> Option<uuid::Uuid> {
    let s = s.strip_prefix("env_").unwrap_or(s);
    uuid::Uuid::parse_str(s).ok()
}

fn default_object_type() -> String {
    "environment".to_string()
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Environment {
    #[serde(serialize_with = "serialize_environment_id")]
    pub id: uuid::Uuid,
    #[serde(rename = "type", default = "default_object_type")]
    pub object_type: String,
    pub name: String,
    #[serde(default)]
    pub description: String,
    #[serde(default)]
    pub metadata: HashMap<String, String>,
    pub config: EnvironmentConfig,
    #[serde(default, skip_serializing)]
    pub image_tag: Option<String>,
    #[serde(default, skip_serializing)]
    pub image_version: i32,
    pub created_at: chrono::DateTime<chrono::Utc>,
    pub updated_at: chrono::DateTime<chrono::Utc>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub archived_at: Option<chrono::DateTime<chrono::Utc>>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct EnvironmentConfig {
    #[serde(rename = "type", default = "default_env_type")]
    pub env_type: String,
    #[serde(default, skip_serializing_if = "Packages::is_empty")]
    pub packages: Packages,
    #[serde(default, skip_serializing_if = "Networking::is_default")]
    pub networking: Networking,
}

fn default_env_type() -> String {
    "cloud".into()
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Packages {
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub apt: Vec<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub pip: Vec<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub npm: Vec<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub cargo: Vec<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub gem: Vec<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub go: Vec<String>,
}

impl Packages {
    pub fn is_empty(&self) -> bool {
        self.apt.is_empty()
            && self.pip.is_empty()
            && self.npm.is_empty()
            && self.cargo.is_empty()
            && self.gem.is_empty()
            && self.go.is_empty()
    }

    pub fn install_commands(&self) -> Vec<String> {
        let mut cmds = Vec::new();
        if !self.apt.is_empty() {
            cmds.push(format!(
                "apt-get update && apt-get install -y {}",
                self.apt.join(" ")
            ));
        }
        if !self.npm.is_empty() {
            cmds.push(format!("npm install -g {}", self.npm.join(" ")));
        }
        if !self.pip.is_empty() {
            cmds.push(format!("pip install {}", self.pip.join(" ")));
        }
        if !self.cargo.is_empty() {
            cmds.push(format!("cargo install {}", self.cargo.join(" ")));
        }
        if !self.gem.is_empty() {
            cmds.push(format!("gem install {}", self.gem.join(" ")));
        }
        if !self.go.is_empty() {
            for pkg in &self.go {
                cmds.push(format!("go install {pkg}"));
            }
        }
        cmds
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct Networking {
    #[serde(rename = "type", default = "default_networking_type")]
    pub net_type: String,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub allowed_hosts: Vec<String>,
    #[serde(default, skip_serializing_if = "skip_networking_bool")]
    pub allow_mcp_servers: bool,
    #[serde(default, skip_serializing_if = "skip_networking_bool")]
    pub allow_package_managers: bool,
}

fn skip_networking_bool(v: &bool) -> bool {
    !*v
}

impl Default for Networking {
    fn default() -> Self {
        Self {
            net_type: default_networking_type(),
            allowed_hosts: Vec::new(),
            allow_mcp_servers: false,
            allow_package_managers: false,
        }
    }
}

impl Networking {
    pub fn is_default(&self) -> bool {
        self.net_type == "unrestricted"
            && self.allowed_hosts.is_empty()
            && !self.allow_mcp_servers
            && !self.allow_package_managers
    }
}

fn default_networking_type() -> String {
    "unrestricted".into()
}

impl<'de> Deserialize<'de> for Networking {
    fn deserialize<D: serde::Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        #[derive(Deserialize)]
        struct RawNetworking {
            #[serde(rename = "type", default = "default_networking_type")]
            net_type: String,
            #[serde(default)]
            allowed_hosts: Vec<String>,
            #[serde(default)]
            allow_mcp_servers: bool,
            #[serde(default)]
            allow_package_managers: bool,
        }

        let mut raw = RawNetworking::deserialize(deserializer)?;
        raw.net_type = normalize_network_type(&raw.net_type).map_err(serde::de::Error::custom)?;
        raw.allowed_hosts = raw
            .allowed_hosts
            .into_iter()
            .map(|h| normalize_allowed_host(&h))
            .collect::<Result<Vec<_>, _>>()
            .map_err(serde::de::Error::custom)?;

        Ok(Networking {
            net_type: raw.net_type,
            allowed_hosts: raw.allowed_hosts,
            allow_mcp_servers: raw.allow_mcp_servers,
            allow_package_managers: raw.allow_package_managers,
        })
    }
}

fn normalize_network_type(raw: &str) -> Result<String, String> {
    match raw {
        "limited" => Ok("limited".to_string()),
        "unrestricted" => Ok("unrestricted".to_string()),
        _ => Err(format!(
            "networking.type must be 'unrestricted' or 'limited', got: {raw}"
        )),
    }
}

fn normalize_allowed_host(raw: &str) -> Result<String, String> {
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        return Err("allowed_hosts entry cannot be empty".to_string());
    }

    if let Some(rest) = trimmed.strip_prefix("https://") {
        let host = rest.trim_end_matches('/');
        if host.is_empty() {
            return Err("allowed_hosts HTTPS host cannot be empty".to_string());
        }
        return Ok(host.to_lowercase());
    }

    if trimmed.contains("://") {
        return Err(format!(
            "allowed_hosts must be 'https://host' or bare hostname, got: {trimmed}"
        ));
    }

    Ok(trimmed.trim_end_matches('/').to_lowercase())
}

impl fmt::Display for Networking {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "Networking(type={}, allowed_hosts={})",
            self.net_type,
            self.allowed_hosts.join(",")
        )
    }
}
