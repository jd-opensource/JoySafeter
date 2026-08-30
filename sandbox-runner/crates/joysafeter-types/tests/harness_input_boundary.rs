#[test]
fn harness_input_has_no_generic_secret_channel() {
    let harness = include_str!("../src/harness.rs");
    assert!(!harness.contains("pub secrets:"));

    for (name, source) in [
        (
            "claude",
            include_str!("../../joysafeter-runtime/src/claude.rs"),
        ),
        (
            "codex",
            include_str!("../../joysafeter-runtime/src/codex.rs"),
        ),
        (
            "native",
            include_str!("../../joysafeter-runtime/src/native.rs"),
        ),
        ("pi", include_str!("../../joysafeter-runtime/src/pi.rs")),
    ] {
        assert!(
            !source.contains("input.secrets"),
            "{name} adapter must not consume a generic secret map"
        );
    }
}
