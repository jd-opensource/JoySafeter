use std::collections::{BTreeMap, BTreeSet};
use std::net::{IpAddr, Ipv4Addr, Ipv6Addr};

use anyhow::Context;
use serde::{Deserialize, Serialize};
use url::Url;
use uuid::Uuid;

pub const POLICY_SCHEMA_VERSION: i32 = 1;
const MAX_POLICIES_PER_GROUP: usize = 10_000;
const MAX_ROUTES_PER_POLICY: usize = 128;
const MAX_HOSTS_PER_POLICY: usize = 256;
const MAX_DENIED_CIDRS: usize = 128;

const ALLOWED_INJECT_HEADERS: [&str; 5] = [
    "authorization",
    "x-api-key",
    "api-key",
    "x-goog-api-key",
    "cookie",
];

const FORBIDDEN_REMOVE_HEADERS: [&str; 18] = [
    "connection",
    "content-length",
    "forwarded",
    "host",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "via",
    "x-forwarded-for",
    "x-forwarded-host",
    "x-forwarded-proto",
    "x-joysafeter-sandbox-id",
    "x-joysafeter-route-id",
    "x-joysafeter-policy-generation",
];

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct SandboxPolicy {
    pub sandbox_id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub project_id: Option<String>,
    pub mode: String,
    pub credential_routes: Vec<CredentialRoute>,
    pub allowed_public_hosts: Vec<String>,
    pub denied_cidrs: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct CredentialRoute {
    pub route_id: String,
    #[serde(default)]
    pub consumer_route_id: String,
    pub kind: String,
    pub match_authority: String,
    pub match_path: PathMatch,
    pub methods: Vec<String>,
    pub upstream: Upstream,
    pub credential_ref: CredentialRef,
    pub inject_header: String,
    pub inject_scheme: InjectScheme,
    pub remove_headers: Vec<String>,
    pub timeout_profile: String,
    pub websocket: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct PathMatch {
    pub kind: String,
    pub value: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct Upstream {
    pub scheme: String,
    pub host: String,
    pub port: u16,
    pub base_path: String,
    pub protocol: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(tag = "kind", rename_all = "lowercase", deny_unknown_fields)]
pub enum CredentialRef {
    Llm {
        secret_name: String,
        secret_key: String,
        #[serde(skip_serializing_if = "Option::is_none")]
        project_id: Option<String>,
    },
    Mcp {
        vault_id: String,
        mcp_server_url: String,
    },
    Git {
        session_id: String,
        mount_name: String,
    },
    External {
        secret_name: String,
        secret_key: String,
        #[serde(skip_serializing_if = "Option::is_none")]
        project_id: Option<String>,
    },
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(tag = "kind", rename_all = "lowercase", deny_unknown_fields)]
pub enum InjectScheme {
    Bearer,
    Basic { username: String },
    Raw,
}

pub fn decode(schema_version: i32, raw: &[u8]) -> anyhow::Result<Vec<SandboxPolicy>> {
    anyhow::ensure!(
        schema_version == POLICY_SCHEMA_VERSION,
        "unsupported egress policy schema version {schema_version}"
    );
    let mut deserializer = serde_json::Deserializer::from_slice(raw);
    let mut policies =
        Vec::<SandboxPolicy>::deserialize(&mut deserializer).context("decode egress policies")?;
    deserializer
        .end()
        .context("egress policy payload contains trailing data")?;
    anyhow::ensure!(
        policies.len() <= MAX_POLICIES_PER_GROUP,
        "egress policy group exceeds {MAX_POLICIES_PER_GROUP} sandboxes"
    );

    let mut seen_sandboxes = BTreeSet::new();
    for (index, policy) in policies.iter_mut().enumerate() {
        policy
            .normalize_and_validate()
            .with_context(|| format!("policy {index}"))?;
        anyhow::ensure!(
            seen_sandboxes.insert(policy.sandbox_id.clone()),
            "duplicate sandbox_id {:?}",
            policy.sandbox_id
        );
    }
    policies.sort_by(|left, right| left.sandbox_id.cmp(&right.sandbox_id));
    Ok(policies)
}

impl SandboxPolicy {
    fn normalize_and_validate(&mut self) -> anyhow::Result<()> {
        self.sandbox_id = normalize_uuid(&self.sandbox_id).context("sandbox_id")?;
        if let Some(project_id) = &mut self.project_id {
            *project_id = normalize_uuid(project_id).context("project_id")?;
        }
        self.mode = self.mode.trim().to_ascii_lowercase();
        anyhow::ensure!(
            matches!(self.mode.as_str(), "limited" | "unrestricted"),
            "mode must be limited or unrestricted"
        );
        anyhow::ensure!(
            self.credential_routes.len() <= MAX_ROUTES_PER_POLICY,
            "credential routes exceed {MAX_ROUTES_PER_POLICY}"
        );
        anyhow::ensure!(
            self.allowed_public_hosts.len() <= MAX_HOSTS_PER_POLICY,
            "allowed public hosts exceed {MAX_HOSTS_PER_POLICY}"
        );
        anyhow::ensure!(
            self.denied_cidrs.len() <= MAX_DENIED_CIDRS,
            "denied CIDRs exceed {MAX_DENIED_CIDRS}"
        );

        let mut seen_routes = BTreeSet::new();
        let mut seen_consumer_matches = BTreeMap::new();
        for (index, route) in self.credential_routes.iter_mut().enumerate() {
            route
                .normalize_and_validate()
                .with_context(|| format!("credential route {index}"))?;
            anyhow::ensure!(
                seen_routes.insert(route.route_id.clone()),
                "duplicate route_id {:?}",
                route.route_id
            );
            for method in &route.methods {
                let key = (
                    route.consumer_route_id.clone(),
                    route.match_path.value.clone(),
                    method.clone(),
                );
                if let Some(existing) = seen_consumer_matches.insert(key, route.route_id.clone()) {
                    anyhow::bail!(
                        "consumer_route_id {:?} has duplicate path/method match in routes {:?} and {:?}",
                        route.consumer_route_id,
                        existing,
                        route.route_id
                    );
                }
            }
        }
        self.credential_routes
            .sort_by(|left, right| left.route_id.cmp(&right.route_id));

        self.allowed_public_hosts = self
            .allowed_public_hosts
            .iter()
            .map(|host| normalize_host_pattern(host))
            .collect::<anyhow::Result<BTreeSet<_>>>()?
            .into_iter()
            .collect();
        self.denied_cidrs = self
            .denied_cidrs
            .iter()
            .map(|cidr| normalize_cidr(cidr))
            .collect::<anyhow::Result<BTreeSet<_>>>()?
            .into_iter()
            .collect();
        Ok(())
    }
}

impl CredentialRoute {
    fn normalize_and_validate(&mut self) -> anyhow::Result<()> {
        self.route_id = self.route_id.trim().to_string();
        anyhow::ensure!(
            valid_route_id(&self.route_id),
            "route_id has invalid format"
        );
        self.consumer_route_id = self.consumer_route_id.trim().to_string();
        if self.consumer_route_id.is_empty() {
            self.consumer_route_id.clone_from(&self.route_id);
        }
        anyhow::ensure!(
            valid_route_id(&self.consumer_route_id),
            "consumer_route_id has invalid format"
        );
        self.kind = self.kind.trim().to_ascii_lowercase();
        anyhow::ensure!(
            matches!(self.kind.as_str(), "llm" | "mcp" | "git" | "external"),
            "unsupported route kind {:?}",
            self.kind
        );
        anyhow::ensure!(
            self.consumer_route_id == self.route_id || self.kind == "external",
            "shared consumer_route_id is supported only for external routes"
        );
        self.match_authority =
            normalize_dns_host(&self.match_authority).context("match_authority")?;
        self.match_path.kind = self.match_path.kind.trim().to_ascii_lowercase();
        anyhow::ensure!(
            matches!(self.match_path.kind.as_str(), "prefix" | "exact"),
            "match_path.kind must be prefix or exact"
        );
        self.match_path.value =
            normalize_path(&self.match_path.value).context("match_path.value")?;

        anyhow::ensure!(
            !self.methods.is_empty() && self.methods.len() <= 8,
            "methods must contain 1 to 8 entries"
        );
        self.methods = self
            .methods
            .iter()
            .map(|method| method.trim().to_ascii_uppercase())
            .map(|method| {
                anyhow::ensure!(
                    matches!(
                        method.as_str(),
                        "GET" | "POST" | "PUT" | "PATCH" | "DELETE" | "HEAD" | "OPTIONS"
                    ),
                    "unsupported HTTP method {method:?}"
                );
                Ok(method)
            })
            .collect::<anyhow::Result<BTreeSet<_>>>()?
            .into_iter()
            .collect();

        self.upstream.normalize_and_validate()?;
        self.credential_ref.normalize_and_validate()?;
        anyhow::ensure!(
            self.credential_ref.kind() == self.kind,
            "credential_ref.kind {:?} does not match route kind {:?}",
            self.credential_ref.kind(),
            self.kind
        );
        self.inject_header = self.inject_header.trim().to_ascii_lowercase();
        anyhow::ensure!(
            ALLOWED_INJECT_HEADERS.contains(&self.inject_header.as_str()),
            "inject_header {:?} is not allowed",
            self.inject_header
        );
        self.inject_scheme.normalize_and_validate()?;

        let mut remove_headers = BTreeSet::from([self.inject_header.clone()]);
        for raw_header in &self.remove_headers {
            let header = raw_header.trim().to_ascii_lowercase();
            anyhow::ensure!(
                valid_header_name(&header),
                "invalid remove header {header:?}"
            );
            anyhow::ensure!(
                !FORBIDDEN_REMOVE_HEADERS.contains(&header.as_str()),
                "remove header {header:?} is reserved"
            );
            remove_headers.insert(header);
        }
        self.remove_headers = remove_headers.into_iter().collect();
        self.timeout_profile = self.timeout_profile.trim().to_ascii_lowercase();
        anyhow::ensure!(
            matches!(
                self.timeout_profile.as_str(),
                "default" | "streaming" | "long_running"
            ),
            "unsupported timeout_profile {:?}",
            self.timeout_profile
        );
        Ok(())
    }
}

impl Upstream {
    fn normalize_and_validate(&mut self) -> anyhow::Result<()> {
        self.scheme = self.scheme.trim().to_ascii_lowercase();
        anyhow::ensure!(
            matches!(self.scheme.as_str(), "http" | "https"),
            "upstream.scheme must be http or https"
        );
        self.host = normalize_dns_host(&self.host).context("upstream.host")?;
        if self.port == 0 {
            self.port = if self.scheme == "https" { 443 } else { 80 };
        }
        self.base_path = normalize_path(&self.base_path).context("upstream.base_path")?;
        self.protocol = self.protocol.trim().to_ascii_lowercase();
        if self.protocol.is_empty() {
            self.protocol = "auto".to_string();
        }
        anyhow::ensure!(
            matches!(self.protocol.as_str(), "auto" | "http1" | "http2"),
            "unsupported upstream.protocol {:?}",
            self.protocol
        );
        Ok(())
    }
}

impl CredentialRef {
    fn kind(&self) -> &'static str {
        match self {
            Self::Llm { .. } => "llm",
            Self::Mcp { .. } => "mcp",
            Self::Git { .. } => "git",
            Self::External { .. } => "external",
        }
    }

    fn normalize_and_validate(&mut self) -> anyhow::Result<()> {
        match self {
            Self::Llm {
                secret_name,
                secret_key,
                project_id,
            }
            | Self::External {
                secret_name,
                secret_key,
                project_id,
            } => {
                *secret_name = normalize_coordinate("secret_name", secret_name)?;
                *secret_key = normalize_coordinate("secret_key", secret_key)?;
                if let Some(project_id) = project_id {
                    *project_id =
                        normalize_uuid(project_id).context("credential_ref.project_id")?;
                }
            }
            Self::Mcp {
                vault_id,
                mcp_server_url,
            } => {
                *vault_id = normalize_uuid(vault_id).context("credential_ref.vault_id")?;
                validate_http_url(mcp_server_url).context("credential_ref.mcp_server_url")?;
                *mcp_server_url = mcp_server_url.trim().to_string();
            }
            Self::Git {
                session_id,
                mount_name,
            } => {
                *session_id = normalize_uuid(session_id).context("credential_ref.session_id")?;
                *mount_name = normalize_coordinate("mount_name", mount_name)?;
            }
        }
        Ok(())
    }
}

impl InjectScheme {
    fn normalize_and_validate(&mut self) -> anyhow::Result<()> {
        if let Self::Basic { username } = self {
            anyhow::ensure!(
                !username.is_empty()
                    && username.len() <= 128
                    && !username.contains(['\r', '\n', ':']),
                "inject_scheme basic requires a safe username"
            );
        }
        Ok(())
    }
}

fn normalize_uuid(raw: &str) -> anyhow::Result<String> {
    Ok(Uuid::parse_str(raw.trim())?.to_string())
}

fn normalize_dns_host(raw: &str) -> anyhow::Result<String> {
    let raw = raw.trim().trim_end_matches('.').to_ascii_lowercase();
    anyhow::ensure!(
        !raw.is_empty() && !raw.contains(['/', '\\', '\0', '\r', '\n']),
        "must be a DNS hostname"
    );
    anyhow::ensure!(
        raw.trim_matches(['[', ']']).parse::<IpAddr>().is_err(),
        "IP literals are not allowed"
    );
    let host = idna::domain_to_ascii(&raw).context("must be a valid IDNA hostname")?;
    anyhow::ensure!(
        host.len() <= 253 && !host.contains(".."),
        "must be a valid IDNA hostname"
    );
    anyhow::ensure!(
        host.split('.').all(|label| {
            !label.is_empty()
                && label.len() <= 63
                && !label.starts_with('-')
                && !label.ends_with('-')
        }),
        "must be a valid DNS hostname"
    );
    Ok(host)
}

fn normalize_host_pattern(raw: &str) -> anyhow::Result<String> {
    let raw = raw.trim();
    if let Some(suffix) = raw.strip_prefix("*.") {
        let host = normalize_dns_host(suffix)?;
        anyhow::ensure!(
            host.contains('.'),
            "wildcard must target a multi-label DNS suffix"
        );
        return Ok(format!("*.{host}"));
    }
    anyhow::ensure!(
        !raw.contains('*'),
        "wildcard is only allowed as the complete left-most label"
    );
    normalize_dns_host(raw)
}

fn normalize_path(raw: &str) -> anyhow::Result<String> {
    let path = match raw.trim() {
        "" => "/",
        value => value,
    };
    anyhow::ensure!(
        path.starts_with('/') && path.len() <= 2048 && !path.contains(['\0', '\r', '\n', '?', '#']),
        "must be an absolute path without query or fragment"
    );
    Ok(path.to_string())
}

pub(crate) fn normalize_cidr(raw: &str) -> anyhow::Result<String> {
    let (address, prefix_len) = raw
        .trim()
        .split_once('/')
        .ok_or_else(|| anyhow::anyhow!("denied CIDR {raw:?} must include a prefix"))?;
    let address: IpAddr = address.parse()?;
    let prefix_len: u32 = prefix_len.parse()?;
    match address {
        IpAddr::V4(address) => {
            anyhow::ensure!(prefix_len <= 32, "IPv4 prefix exceeds 32");
            let mask = if prefix_len == 0 {
                0
            } else {
                u32::MAX << (32 - prefix_len)
            };
            Ok(format!(
                "{}/{}",
                Ipv4Addr::from(u32::from(address) & mask),
                prefix_len
            ))
        }
        IpAddr::V6(address) => {
            anyhow::ensure!(prefix_len <= 128, "IPv6 prefix exceeds 128");
            let mask = if prefix_len == 0 {
                0
            } else {
                u128::MAX << (128 - prefix_len)
            };
            Ok(format!(
                "{}/{}",
                Ipv6Addr::from(u128::from(address) & mask),
                prefix_len
            ))
        }
    }
}

fn validate_http_url(raw: &str) -> anyhow::Result<()> {
    let parsed = Url::parse(raw.trim())?;
    anyhow::ensure!(
        matches!(parsed.scheme(), "http" | "https")
            && parsed.host_str().is_some()
            && parsed.username().is_empty()
            && parsed.password().is_none(),
        "must be an HTTP(S) URL without userinfo"
    );
    normalize_dns_host(parsed.host_str().expect("host checked above"))?;
    Ok(())
}

fn normalize_coordinate(name: &str, raw: &str) -> anyhow::Result<String> {
    let value = raw.trim();
    anyhow::ensure!(
        !value.is_empty() && value.len() <= 255 && !value.contains(['\0', '\r', '\n']),
        "credential_ref.{name} is invalid"
    );
    Ok(value.to_string())
}

fn valid_route_id(value: &str) -> bool {
    let mut bytes = value.bytes();
    let Some(first) = bytes.next() else {
        return false;
    };
    value.len() <= 128
        && first.is_ascii_alphanumeric()
        && bytes.all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
}

fn valid_header_name(value: &str) -> bool {
    let mut bytes = value.bytes();
    let Some(first) = bytes.next() else {
        return false;
    };
    value.len() <= 127
        && (first.is_ascii_lowercase() || first.is_ascii_digit())
        && bytes.all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'-')
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::*;

    fn valid_policy() -> serde_json::Value {
        json!([{
            "sandbox_id": "018ff000-0000-7000-8000-000000000001",
            "project_id": "018ff000-0000-7000-8000-000000000002",
            "mode": " LIMITED ",
            "credential_routes": [{
                "route_id": "llm.primary",
                "consumer_route_id": "",
                "kind": "LLM",
                "match_authority": "API.Example.COM.",
                "match_path": {"kind": "PREFIX", "value": "/v1"},
                "methods": ["post", "GET", "POST"],
                "upstream": {
                    "scheme": "HTTPS",
                    "host": "UPSTREAM.Example.COM",
                    "port": 0,
                    "base_path": "/api",
                    "protocol": ""
                },
                "credential_ref": {
                    "kind": "llm",
                    "secret_name": " provider ",
                    "secret_key": " token ",
                    "project_id": "018ff000-0000-7000-8000-000000000002"
                },
                "inject_header": "Authorization",
                "inject_scheme": {"kind": "bearer"},
                "remove_headers": ["X-API-Key", "authorization"],
                "timeout_profile": "STREAMING",
                "websocket": false
            }],
            "allowed_public_hosts": ["*.Example.COM", "downloads.example.com"],
            "denied_cidrs": ["10.1.2.3/8", "2001:db8::1/64"]
        }])
    }

    #[test]
    fn strict_decode_normalizes_and_sorts() {
        let policies = decode(
            POLICY_SCHEMA_VERSION,
            &serde_json::to_vec(&valid_policy()).unwrap(),
        )
        .unwrap();
        let policy = &policies[0];
        assert_eq!(policy.mode, "limited");
        assert_eq!(
            policy.allowed_public_hosts,
            ["*.example.com", "downloads.example.com"]
        );
        assert_eq!(policy.denied_cidrs, ["10.0.0.0/8", "2001:db8::/64"]);
        let route = &policy.credential_routes[0];
        assert_eq!(route.consumer_route_id, route.route_id);
        assert_eq!(route.methods, ["GET", "POST"]);
        assert_eq!(route.upstream.port, 443);
        assert_eq!(route.upstream.protocol, "auto");
        assert_eq!(route.remove_headers, ["authorization", "x-api-key"]);
    }

    #[test]
    fn rejects_unknown_and_secret_bearing_fields() {
        let mut document = valid_policy();
        document[0]["credential_routes"][0]["credential_ref"]["token"] = json!("secret");
        let error = decode(
            POLICY_SCHEMA_VERSION,
            &serde_json::to_vec(&document).unwrap(),
        )
        .unwrap_err();
        assert!(error.to_string().contains("decode egress policies"));
    }

    #[test]
    fn rejects_ip_upstream_and_reserved_headers() {
        let mut document = valid_policy();
        document[0]["credential_routes"][0]["upstream"]["host"] = json!("127.0.0.1");
        assert!(decode(
            POLICY_SCHEMA_VERSION,
            &serde_json::to_vec(&document).unwrap()
        )
        .is_err());

        let mut document = valid_policy();
        document[0]["credential_routes"][0]["remove_headers"] = json!(["host"]);
        assert!(decode(
            POLICY_SCHEMA_VERSION,
            &serde_json::to_vec(&document).unwrap()
        )
        .is_err());
    }

    #[test]
    fn rejects_duplicate_consumer_match_and_trailing_documents() {
        let mut document = valid_policy();
        document[0]["credential_routes"][0]["consumer_route_id"] = json!("shared.external");
        document[0]["credential_routes"][0]["kind"] = json!("external");
        document[0]["credential_routes"][0]["credential_ref"]["kind"] = json!("external");
        let mut duplicate = document[0]["credential_routes"][0].clone();
        duplicate["route_id"] = json!("llm.secondary");
        document[0]["credential_routes"]
            .as_array_mut()
            .unwrap()
            .push(duplicate);
        assert!(decode(
            POLICY_SCHEMA_VERSION,
            &serde_json::to_vec(&document).unwrap()
        )
        .is_err());

        let mut raw = serde_json::to_vec(&valid_policy()).unwrap();
        raw.extend_from_slice(b" []");
        assert!(decode(POLICY_SCHEMA_VERSION, &raw).is_err());
    }
}
