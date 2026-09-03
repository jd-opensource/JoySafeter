use super::*;

#[test]
fn node_identity_is_canonicalized_and_bounded() {
    assert_eq!(
        validated_node_id(" node-a:1 ".to_string()).unwrap(),
        "node-a:1"
    );
    assert!(validated_node_id(String::new()).is_err());
    assert!(validated_node_id("node/a".to_string()).is_err());
    assert!(validated_node_id("a".repeat(MAX_NODE_ID_BYTES + 1)).is_err());
}
