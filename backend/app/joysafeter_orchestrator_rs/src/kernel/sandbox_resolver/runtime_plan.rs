use std::collections::HashMap;

use url::Url;

use crate::kernel::credentials::runtime_projection::EnvironmentRow;

use super::model::ExpectedFingerprint;

pub(crate) fn apply_sandbox_timezone(env: &mut HashMap<String, String>, platform_timezone: &str) {
    let platform_timezone = platform_timezone.trim();
    if !platform_timezone.is_empty() {
        env.entry("TZ".to_string())
            .or_insert_with(|| platform_timezone.to_string());
    }
}

pub(crate) fn apply_claude_code_sandbox_privacy(env: &mut HashMap<String, String>) {
    env.entry("DISABLE_TELEMETRY".to_string())
        .or_insert_with(|| "1".to_string());
    env.entry("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC".to_string())
        .or_insert_with(|| "1".to_string());
}

pub(crate) fn runtime_fingerprint_matches(
    config: Option<&serde_json::Value>,
    sandbox_image: Option<&str>,
    expected: &ExpectedFingerprint,
) -> bool {
    let Some(config) = config else {
        return sandbox_image == Some(expected.image.as_str());
    };
    match config.get("fingerprint") {
        Some(actual) => {
            let mut actual_runtime = actual.clone();
            if let Some(obj) = actual_runtime.as_object_mut() {
                obj.remove("egress_policy_hash");
            }
            let mut expected_runtime = expected.to_json();
            if let Some(obj) = expected_runtime.as_object_mut() {
                obj.remove("egress_policy_hash");
            }
            actual_runtime == expected_runtime
        }
        None => sandbox_image == Some(expected.image.as_str()),
    }
}

pub(crate) fn provisioning_config(
    stage: &str,
    progress: i64,
    message: &str,
    complete: bool,
    expected: &ExpectedFingerprint,
    egress_proxy_token: Option<&str>,
) -> serde_json::Value {
    let mut config = serde_json::json!({
        "provisioning": {
            "stage": stage,
            "progress": progress,
            "message": message,
            "complete": complete,
            "error": false,
        },
        "fingerprint": expected.to_json(),
    });

    if let Some(token) = egress_proxy_token {
        if let Some(obj) = config.as_object_mut() {
            obj.insert(
                "egress_proxy_token".to_string(),
                serde_json::Value::String(token.to_string()),
            );
        }
    }

    config
}

/// Generate a random runner token (hex-encoded 32 bytes).
pub(crate) fn generate_runner_token() -> String {
    let random_bytes: [u8; 32] = rand::random();
    hex::encode(random_bytes)
}

pub(crate) fn effective_networking_config(
    networking: Option<serde_json::Value>,
    envoy_enabled: bool,
    environment: Option<&EnvironmentRow>,
) -> anyhow::Result<Option<serde_json::Value>> {
    match networking_type(networking.as_ref()) {
        Some("limited") => networking
            .map(|networking| sanitize_limited_networking(networking, environment))
            .transpose(),
        Some("unrestricted" | "disabled") => Ok(networking),
        Some(other) => anyhow::bail!("unsupported sandbox networking.type: {other}"),
        None if envoy_enabled => {
            let mut effective = networking.unwrap_or_else(|| serde_json::json!({}));
            let Some(object) = effective.as_object_mut() else {
                anyhow::bail!(
                    "sandbox networking config must be an object when Envoy default-limited networking is enabled"
                );
            };
            object.insert(
                "type".to_string(),
                serde_json::Value::String("limited".to_string()),
            );
            sanitize_limited_networking(effective, environment).map(Some)
        }
        None => Ok(networking),
    }
}

pub(crate) fn networking_type(networking: Option<&serde_json::Value>) -> Option<&str> {
    networking.and_then(|value| value.get("type").and_then(|value| value.as_str()))
}

pub(crate) fn sanitize_limited_networking(
    mut networking: serde_json::Value,
    environment: Option<&EnvironmentRow>,
) -> anyhow::Result<serde_json::Value> {
    if networking_type(Some(&networking)) != Some("limited") {
        return Ok(networking);
    }

    let mut allowed_hosts = networking
        .get("allowed_hosts")
        .and_then(|value| value.as_array())
        .map(|values| {
            values
                .iter()
                .filter_map(|value| value.as_str().map(ToOwned::to_owned))
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();

    // Remove external egress service hosts from allowlist. Each external service
    // emits a transparent credential vhost keyed on its real host. If the same
    // host also appears in allowed_hosts, the `allowed` vhost would declare a
    // duplicate domain and Envoy rejects the config.
    if let Some(egress_hosts) = environment
        .and_then(|env| env.config.get("egress_services"))
        .and_then(|v| v.as_array())
    {
        let external_hosts: Vec<String> = egress_hosts
            .iter()
            .filter_map(|svc| svc.get("base_url").and_then(|v| v.as_str()))
            .filter_map(|url| extract_host(url))
            .collect();
        allowed_hosts.retain(|h| !external_hosts.iter().any(|eh| eh == h));
    }

    let Some(object) = networking.as_object_mut() else {
        return Ok(networking);
    };
    object.insert(
        "allowed_hosts".to_string(),
        serde_json::Value::Array(
            allowed_hosts
                .into_iter()
                .map(serde_json::Value::String)
                .collect(),
        ),
    );
    Ok(networking)
}

pub(crate) fn extract_host(raw_url: &str) -> Option<String> {
    Url::parse(raw_url)
        .ok()
        .and_then(|url| url.host_str().map(ToOwned::to_owned))
}

pub(crate) fn prefix_allows(sub_path: &str, prefixes: &[serde_json::Value]) -> bool {
    let sub_path = sub_path.trim_matches('/');
    if prefixes.is_empty() {
        return sub_path.is_empty();
    }
    prefixes.iter().any(|prefix| {
        let Some(prefix) = prefix.as_str() else {
            return false;
        };
        let prefix = prefix.trim_matches('/');
        prefix.is_empty() || sub_path == prefix || sub_path.starts_with(&format!("{prefix}/"))
    })
}

pub(crate) fn effective_prefixes(
    prefix_sets: Vec<Vec<serde_json::Value>>,
) -> Vec<serde_json::Value> {
    let mut constrained: Vec<Vec<serde_json::Value>> = prefix_sets
        .into_iter()
        .filter(|prefixes| !prefixes.is_empty())
        .collect();
    if constrained.is_empty() {
        return Vec::new();
    }
    let mut candidates = constrained.pop().unwrap_or_default();
    while let Some(prefixes) = constrained.pop() {
        let mut next = Vec::new();
        for candidate in &candidates {
            let Some(candidate_str) = candidate.as_str() else {
                continue;
            };
            if prefix_allows(candidate_str, &prefixes) && !next.contains(candidate) {
                next.push(candidate.clone());
            }
        }
        for prefix in &prefixes {
            let Some(prefix_str) = prefix.as_str() else {
                continue;
            };
            if prefix_allows(prefix_str, &candidates) && !next.contains(prefix) {
                next.push(prefix.clone());
            }
        }
        candidates = next;
    }
    candidates
}
