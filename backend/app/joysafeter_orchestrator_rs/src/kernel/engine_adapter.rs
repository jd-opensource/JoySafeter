/// Data-driven engine adapter registry.
///
/// Engine-specific (claude / codex / native / pi) decisions that were previously
/// scattered across multiple match arms are now encoded in a single registry.
/// Adding a new engine adapter is a table entry rather than touching multiple
/// files.

/// Specification for a single engine adapter.
pub struct EngineSpec {
    /// Engine kind identifier (matches `input.provider`).
    pub engine_kind: &'static str,

    /// Whether conversation history injection applies (vs harness resume).
    pub injects_conversation_history: bool,

    /// Protocols this engine can execute, using canonical Catalog IDs.
    pub supported_protocol_ids: &'static [&'static str],
}

/// Returns the ordered registry of engine adapters.
pub fn engine_registry() -> &'static [EngineSpec] {
    static REGISTRY: &[EngineSpec] = &[
        EngineSpec {
            engine_kind: "claude",
            injects_conversation_history: true,
            supported_protocol_ids: &["anthropic_messages"],
        },
        EngineSpec {
            engine_kind: "codex",
            injects_conversation_history: true,
            supported_protocol_ids: &["openai_responses"],
        },
        EngineSpec {
            engine_kind: "native",
            injects_conversation_history: true,
            supported_protocol_ids: &["anthropic_messages", "openai_responses", "chat_completions"],
        },
        EngineSpec {
            engine_kind: "pi",
            injects_conversation_history: true,
            supported_protocol_ids: &["anthropic_messages", "openai_responses", "chat_completions"],
        },
    ];
    REGISTRY
}

/// Look up the engine spec by kind. Returns `None` for unknown engines.
pub fn engine_spec(engine_kind: &str) -> Option<&'static EngineSpec> {
    engine_registry()
        .iter()
        .find(|s| s.engine_kind == engine_kind)
}

#[cfg(test)]
mod tests {
    use crate::kernel::llm_catalog::catalog;

    #[test]
    fn pi_engine_is_registered() {
        assert!(super::engine_spec("pi").is_some());
    }

    #[test]
    fn engine_protocol_matrix_matches_catalog() {
        let catalog = catalog().expect("catalog must parse");

        for engine in &catalog.engines {
            let spec = super::engine_spec(&engine.id).expect("catalog engine must have adapter");
            assert_eq!(
                spec.supported_protocol_ids,
                engine
                    .supported_protocol_ids
                    .iter()
                    .map(String::as_str)
                    .collect::<Vec<_>>()
            );
        }
        assert_eq!(super::engine_registry().len(), catalog.engines.len());
    }
}
