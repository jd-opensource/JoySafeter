use super::*;

#[test]
fn keyring_accepts_rotation_keys_without_retaining_them_in_debug_output() {
    let active = "abcdefghijklmnopqrstuvwxyz012345";
    let previous = "zyxwvutsrqponmlkjihgfedcba543210";
    let raw = format!(r#"{{"active":"{active}","previous":"{previous}"}}"#);
    let keyring = XdsAuthKeyring::parse(&raw, "active").expect("valid keyring");
    let authenticator = SharedTokenAuthenticator::new(keyring.clone());

    assert!(authenticator.authenticate_value(Some(active)).is_ok());
    assert!(authenticator.authenticate_value(Some(previous)).is_ok());
    assert!(authenticator
        .authenticate_value(Some("invalid-token-value-that-is-long"))
        .is_err());
    let debug = format!("{keyring:?}");
    assert!(!debug.contains(active));
    assert!(!debug.contains(previous));
}
