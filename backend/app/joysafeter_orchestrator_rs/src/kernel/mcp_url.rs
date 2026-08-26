//! Single canonical normal form for MCP server URLs.
//!
//! This is the authoritative normalization contract shared with the Python
//! `normalize_mcp_url` (see `backend/app/joysafeter_shared/mcp_url.py`). Both
//! languages must produce byte-identical output for the same input so that the
//! DB uniqueness constraint `(group_id, normalized_mcp_server_url)` and the
//! runtime credential match agree on ONE normal form (replacing the old
//! multi-candidate-key matching in `harness_input_builder`).
//!
//! Contract:
//!   1. Trim surrounding whitespace.
//!   2. Parse as a URL; lowercase the scheme and host.
//!   3. Remove a default port (`:443` for https, `:80` for http); keep others.
//!   4. Strip a single trailing `/` from the path; the empty/`"/"` path
//!      normalizes to empty (so `https://h.com/` == `https://h.com`).
//!   5. Keep the query string (query is part of MCP endpoint identity).
//!   6. Drop the fragment.
//!   7. Return the reassembled URL string.
//! If the input does not parse as a URL, return the trimmed input unchanged.

use url::Url;

fn default_port(scheme: &str) -> Option<u16> {
    match scheme {
        "https" => Some(443),
        "http" => Some(80),
        _ => None,
    }
}

/// Normalizes an MCP server URL to the single canonical form. See module docs.
pub fn normalize(raw: &str) -> String {
    let trimmed = raw.trim();

    let mut url = match Url::parse(trimmed) {
        Ok(url) => url,
        Err(_) => return trimmed.to_string(),
    };

    // Reject inputs that parse but lack a host (e.g. `mailto:` or `foo:bar`);
    // treat them as non-URLs and return the trimmed input unchanged so both
    // languages agree.
    if url.host_str().is_none() {
        return trimmed.to_string();
    }

    // The `url` crate already lowercases the scheme and host on parse, and
    // strips default ports for special schemes (http/https). We defensively
    // clear the port when it matches the scheme default to stay explicit.
    if let (Some(port), Some(def)) = (url.port(), default_port(url.scheme())) {
        if port == def {
            let _ = url.set_port(None);
        }
    }

    // Drop the fragment.
    url.set_fragment(None);

    // Strip a single trailing slash; the empty/"/" path becomes "".
    let path = url.path().to_string();
    let new_path = if path == "/" {
        ""
    } else if let Some(stripped) = path.strip_suffix('/') {
        stripped
    } else {
        &path
    };
    url.set_path(new_path);

    // `Url` re-appends a trailing "/" for an empty path on special schemes;
    // strip it from the final string so `https://h.com/` == `https://h.com`.
    let out = url.to_string();
    if url.path().is_empty() || url.path() == "/" {
        // Remove exactly one trailing slash that sits right before an optional
        // query. Since query is kept and fragment is dropped, the only place a
        // path slash can appear here is directly after the authority.
        if url.query().is_none() {
            return out.strip_suffix('/').unwrap_or(&out).to_string();
        }
        // With a query present the serialized form is `scheme://host/?query`;
        // remove the slash that precedes the `?`.
        return out.replacen("/?", "?", 1);
    }
    out
}

/// Builds the canonical identity used by transport routing. Unlike
/// [`normalize`], this preserves the configured request target exactly,
/// including a trailing slash and the original query ordering.
pub fn routing_identity(raw: &str) -> Option<String> {
    let trimmed = raw.trim();
    let mut url = Url::parse(trimmed).ok()?;
    if !matches!(url.scheme(), "http" | "https")
        || url.host_str().is_none()
        || !url.username().is_empty()
        || url.password().is_some()
        || url.fragment().is_some()
    {
        return None;
    }

    if let (Some(port), Some(default)) = (url.port(), default_port(url.scheme())) {
        if port == default {
            url.set_port(None).ok()?;
        }
    }

    Some(url.to_string())
}

#[cfg(test)]
mod tests {
    use super::{normalize, routing_identity};
    use std::path::PathBuf;

    #[derive(serde::Deserialize)]
    struct Vector {
        raw: String,
        normalized: String,
    }

    /// Loads the shared `mcp_url_vectors.json` — the SAME fixture the Python
    /// `test_mcp_url.py` asserts against — and proves cross-language parity:
    /// every `raw` must normalize to its recorded `normalized` form.
    #[test]
    fn matches_shared_vectors() {
        // CARGO_MANIFEST_DIR = backend/app/joysafeter_orchestrator_rs;
        // fixture lives at backend/tests/fixtures/mcp_url_vectors.json.
        let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../tests/fixtures/mcp_url_vectors.json");
        let vectors: Vec<Vector> =
            serde_json::from_str(&std::fs::read_to_string(&path).expect("read mcp url vectors"))
                .expect("parse mcp url vectors");
        assert!(!vectors.is_empty(), "vectors fixture must not be empty");

        for v in &vectors {
            assert_eq!(
                normalize(&v.raw),
                v.normalized,
                "normalize({:?}) mismatch",
                v.raw
            );
        }
    }

    #[test]
    fn trailing_slash_and_bare_are_equal() {
        assert_eq!(
            normalize("https://example.com/mcp/"),
            normalize("https://example.com/mcp")
        );
        assert_eq!(
            normalize("https://example.com/"),
            normalize("https://example.com")
        );
    }

    #[test]
    fn routing_identity_preserves_request_target_identity() {
        assert_eq!(
            routing_identity(" HTTPS://Example.COM:443/mcp?b=2&a=1&a=3 ").as_deref(),
            Some("https://example.com/mcp?b=2&a=1&a=3")
        );
        assert_ne!(
            routing_identity("https://example.com/mcp"),
            routing_identity("https://example.com/mcp/")
        );
    }

    #[test]
    fn default_port_removed_but_custom_kept() {
        assert_eq!(normalize("https://h.com:443/x"), "https://h.com/x");
        assert_eq!(normalize("https://h.com:8443/x"), "https://h.com:8443/x");
    }

    #[test]
    fn non_url_returned_unchanged() {
        assert_eq!(normalize("not a url"), "not a url");
        assert_eq!(normalize("  not a url  "), "not a url");
    }
}
