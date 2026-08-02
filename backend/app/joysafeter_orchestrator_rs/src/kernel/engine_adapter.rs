//! Data-driven engine adapter registry.
//!
//! Engine-specific (claude / codex / native) decisions that were previously
//! scattered across multiple match arms are now encoded in a single registry.
//! Adding a new engine adapter is a table entry rather than touching multiple
//! files.

/// Specification for a single engine adapter.
pub struct EngineSpec {
    /// Engine kind identifier (matches `input.provider`).
    pub engine_kind: &'static str,

    /// Whether conversation history injection applies (vs harness resume).
    pub injects_conversation_history: bool,

    /// Secret keys to read for the model name, in priority order. First key
    /// present in the secrets map wins.
    pub model_secret_keys: &'static [&'static str],
}

/// Returns the ordered registry of engine adapters.
pub fn engine_registry() -> &'static [EngineSpec] {
    static REGISTRY: &[EngineSpec] = &[
        EngineSpec {
            engine_kind: "claude",
            injects_conversation_history: true,
            model_secret_keys: &["ANTHROPIC_MODEL", "MODEL"],
        },
        EngineSpec {
            engine_kind: "codex",
            injects_conversation_history: true,
            model_secret_keys: &["OPENAI_MODEL"],
        },
        EngineSpec {
            engine_kind: "native",
            injects_conversation_history: true,
            model_secret_keys: &["ANTHROPIC_MODEL", "MODEL"],
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
