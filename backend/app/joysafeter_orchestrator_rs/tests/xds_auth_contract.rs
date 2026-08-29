use joysafeter_orchestrator::xds::auth::{
    AdsAuthenticator, StaticTokenAdsAuthenticator, ADS_NODE_ID_HEADER,
};
use tonic::metadata::{Ascii, MetadataMap, MetadataValue};

fn metadata(token: Option<&str>, node_id: Option<&str>) -> MetadataMap {
    let mut metadata = MetadataMap::new();
    if let Some(token) = token {
        metadata.insert(
            "authorization",
            MetadataValue::<Ascii>::try_from(format!("Bearer {token}"))
                .expect("valid authorization metadata"),
        );
    }
    if let Some(node_id) = node_id {
        metadata.insert(
            ADS_NODE_ID_HEADER,
            MetadataValue::<Ascii>::try_from(node_id).expect("valid node metadata"),
        );
    }
    metadata
}

#[test]
fn static_ads_authenticator_rejects_missing_or_invalid_credentials() {
    let authenticator = StaticTokenAdsAuthenticator::new("top-secret").unwrap();

    assert!(authenticator
        .authenticate(&metadata(None, Some("node-a")))
        .is_err());
    assert!(authenticator
        .authenticate(&metadata(Some("wrong"), Some("node-a")))
        .is_err());
    assert!(authenticator
        .authenticate(&metadata(Some("top-secret"), None))
        .is_err());
    assert!(authenticator
        .authenticate(&metadata(Some("top-secret"), Some("")))
        .is_err());
}

#[test]
fn static_ads_authenticator_returns_authenticated_node() {
    let authenticator = StaticTokenAdsAuthenticator::new("top-secret").unwrap();

    let identity = authenticator
        .authenticate(&metadata(Some("top-secret"), Some("worker-node-a")))
        .expect("valid ADS credentials");

    assert_eq!(identity.node_id().as_str(), "worker-node-a");
}

#[test]
fn static_ads_authenticator_rejects_empty_server_secret() {
    assert!(StaticTokenAdsAuthenticator::new("  ").is_err());
}
