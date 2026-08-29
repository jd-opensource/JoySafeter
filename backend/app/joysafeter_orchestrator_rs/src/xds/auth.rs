use subtle::ConstantTimeEq;
use tonic::metadata::MetadataMap;
use tonic::Status;

use super::model::NodeId;

pub const ADS_NODE_ID_HEADER: &str = "x-joysafeter-node-id";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AuthenticatedNode {
    node_id: NodeId,
}

impl AuthenticatedNode {
    pub fn node_id(&self) -> &NodeId {
        &self.node_id
    }
}

pub trait AdsAuthenticator: Send + Sync + 'static {
    fn authenticate(&self, metadata: &MetadataMap) -> Result<AuthenticatedNode, Status>;
}

#[derive(Clone)]
pub struct StaticTokenAdsAuthenticator {
    token: Box<[u8]>,
}

impl StaticTokenAdsAuthenticator {
    pub fn new(token: impl AsRef<str>) -> anyhow::Result<Self> {
        let token = token.as_ref().trim();
        if token.is_empty() {
            anyhow::bail!("xDS authentication token must not be empty");
        }
        Ok(Self {
            token: token.as_bytes().to_vec().into_boxed_slice(),
        })
    }
}

impl AdsAuthenticator for StaticTokenAdsAuthenticator {
    fn authenticate(&self, metadata: &MetadataMap) -> Result<AuthenticatedNode, Status> {
        let authorization = metadata
            .get("authorization")
            .ok_or_else(|| Status::unauthenticated("missing ADS authorization"))?
            .to_str()
            .map_err(|_| Status::unauthenticated("invalid ADS authorization"))?;
        let supplied = authorization
            .strip_prefix("Bearer ")
            .ok_or_else(|| Status::unauthenticated("invalid ADS authorization scheme"))?
            .as_bytes();
        if supplied.len() != self.token.len() || supplied.ct_eq(&self.token).unwrap_u8() != 1 {
            return Err(Status::unauthenticated("invalid ADS authorization"));
        }

        let node_id = metadata
            .get(ADS_NODE_ID_HEADER)
            .ok_or_else(|| Status::unauthenticated("missing authenticated ADS node id"))?
            .to_str()
            .map_err(|_| Status::unauthenticated("invalid authenticated ADS node id"))?;
        let node_id = NodeId::new(node_id)
            .map_err(|_| Status::unauthenticated("invalid authenticated ADS node id"))?;

        Ok(AuthenticatedNode { node_id })
    }
}
