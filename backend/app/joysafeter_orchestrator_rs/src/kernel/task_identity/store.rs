use async_trait::async_trait;
use uuid::Uuid;

use crate::ids::{ProjectId, TaskId, UserId};

use super::error::TaskIdentityContextError;

#[derive(Debug)]
pub(crate) struct StoredIdentityMaterial {
    pub(crate) user_id: UserId,
    pub(crate) user_name: Option<String>,
    pub(crate) credential_kind: String,
    pub(crate) encrypted_credential: String,
}

#[derive(Debug)]
pub(crate) struct ClaimedIdentityMaterial {
    pub(crate) resolution_id: Uuid,
    pub(crate) material: StoredIdentityMaterial,
}

#[derive(Debug)]
pub(crate) enum IdentityMaterialClaim {
    Claimed(ClaimedIdentityMaterial),
    Busy,
    Unavailable,
}

#[derive(Debug)]
pub(crate) struct TaskActorIdentity {
    pub(crate) user_id: UserId,
    pub(crate) user_name: Option<String>,
}

#[async_trait]
pub(crate) trait TaskIdentityStore: Send + Sync + std::fmt::Debug {
    async fn claim_material(
        &self,
        task_id: TaskId,
        project_id: ProjectId,
    ) -> Result<IdentityMaterialClaim, TaskIdentityContextError>;

    async fn complete_claim(
        &self,
        task_id: TaskId,
        project_id: ProjectId,
        resolution_id: Uuid,
    ) -> Result<(), TaskIdentityContextError>;

    async fn release_claim(
        &self,
        task_id: TaskId,
        project_id: ProjectId,
        resolution_id: Uuid,
    ) -> Result<(), TaskIdentityContextError>;

    async fn load_task_actor(
        &self,
        task_id: TaskId,
        project_id: ProjectId,
    ) -> Result<TaskActorIdentity, TaskIdentityContextError>;
}
