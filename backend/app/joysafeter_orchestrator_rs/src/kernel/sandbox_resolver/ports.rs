use async_trait::async_trait;

use crate::ids::{AgentId, ProjectId, SessionId, TaskId};

use super::model::ResolvedSandbox;

#[async_trait]
pub(crate) trait SandboxResolution: Send + Sync {
    async fn resolve(
        &self,
        task_id: TaskId,
        session_id: Option<SessionId>,
        agent_id: Option<AgentId>,
        project_id: Option<ProjectId>,
    ) -> anyhow::Result<ResolvedSandbox>;
}
