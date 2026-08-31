use crate::grpc::{proto, tool_policy};
use crate::ids::TaskId;
use crate::kernel::harness_contract::{
    HarnessCustomTool, HarnessFileMount, HarnessFileRef, HarnessInput, HarnessMcpServer,
    HarnessMcpTransport, HarnessMemoryFile, HarnessMemoryStoreMount, HarnessRepository,
    HarnessSkillArchive,
};

pub(crate) fn setup_sandbox(input: &HarnessInput, setup_id: String) -> proto::SetupSandbox {
    proto::SetupSandbox {
        skills: input.skills.iter().map(encode_skill_archive).collect(),
        mcp_servers: input.mcp_servers.iter().map(encode_mcp_server).collect(),
        custom_tools: input.custom_tools.iter().map(encode_custom_tool).collect(),
        setup_commands: input.setup_commands.clone(),
        work_dir: input.work_dir.clone(),
        env: input.env.clone(),
        provider: input.provider.clone(),
        model: input.model.clone(),
        memory_system_prompt: input.memory_system_prompt.clone(),
        memory_mounts: input
            .memory_mounts
            .iter()
            .map(encode_memory_mount)
            .collect(),
        repos: input.repos.iter().map(encode_repository).collect(),
        tool_policy: Some(tool_policy::encode(&input.tool_policy)),
        setup_id,
        runtime_config_generation: input.runtime_config_generation,
    }
}

pub(crate) fn start_task(
    input: &HarnessInput,
    task_id: TaskId,
    timeout_seconds: u64,
) -> proto::StartTask {
    proto::StartTask {
        task_id: task_id.to_string(),
        provider: input.provider.clone(),
        prompt: input.prompt.clone(),
        system_prompt: input.system_prompt.clone(),
        harness_session_id: input.harness_session_id.clone(),
        model: input.model.clone(),
        max_turns: Some(input.max_turns),
        timeout_seconds,
        env: input.env.clone(),
        mcp_servers: input.mcp_servers.iter().map(encode_mcp_server).collect(),
        repos: input.repos.iter().map(encode_repository).collect(),
        work_dir: input.work_dir.clone(),
        setup_commands: input.setup_commands.clone(),
        custom_tools: input.custom_tools.iter().map(encode_custom_tool).collect(),
        system_prompt_mode: if input.system_prompt_mode.is_empty() {
            None
        } else {
            Some(input.system_prompt_mode.clone())
        },
        files: input.files.iter().map(encode_file_mount).collect(),
        file_refs: input.file_refs.iter().map(encode_file_ref).collect(),
        tool_policy: Some(tool_policy::encode(&input.tool_policy)),
        runtime_config_generation: input.runtime_config_generation,
    }
}

fn encode_mcp_server(server: &HarnessMcpServer) -> proto::McpConfig {
    proto::McpConfig {
        name: server.name.clone(),
        command: server.command.clone(),
        args: server.args.clone(),
        env: server.env.clone(),
        url: server.url.clone(),
        headers: server.headers.clone(),
        transport: match server.transport {
            HarnessMcpTransport::StreamableHttp => proto::McpTransport::StreamableHttp as i32,
            HarnessMcpTransport::Sse => proto::McpTransport::Sse as i32,
            HarnessMcpTransport::LocalStdio => proto::McpTransport::LocalStdio as i32,
        },
    }
}

fn encode_custom_tool(tool: &HarnessCustomTool) -> proto::CustomTool {
    proto::CustomTool {
        name: tool.name.clone(),
        description: tool.description.clone(),
        input_schema_json: tool.input_schema_json.clone(),
    }
}

fn encode_skill_archive(archive: &HarnessSkillArchive) -> proto::SkillArchive {
    proto::SkillArchive {
        name: archive.name.clone(),
        tar_gz: archive.tar_gz.clone(),
        target: archive.target.clone(),
        skill_id: archive.skill_id.clone(),
        skill_version: archive.skill_version.clone(),
        skill_version_id: archive.skill_version_id.clone(),
        skill_name: archive.skill_name.clone(),
        skill_source_type: archive.skill_source_type.clone(),
        security_scan_id: archive.security_scan_id.clone(),
        target_hash: archive.target_hash.clone(),
        artifact_hash: archive.artifact_hash.clone(),
    }
}

fn encode_memory_mount(mount: &HarnessMemoryStoreMount) -> proto::MemoryStoreMount {
    proto::MemoryStoreMount {
        mount_name: mount.mount_name.clone(),
        mount_path: mount.mount_path.clone(),
        access: mount.access.clone(),
        files: mount.files.iter().map(encode_memory_file).collect(),
    }
}

fn encode_memory_file(file: &HarnessMemoryFile) -> proto::MemoryFile {
    proto::MemoryFile {
        relative_path: file.relative_path.clone(),
        content: file.content.clone(),
    }
}

fn encode_file_mount(file: &HarnessFileMount) -> proto::FileMount {
    proto::FileMount {
        path: file.path.clone(),
        content: file.content.clone(),
        filename: file.filename.clone(),
    }
}

fn encode_file_ref(file: &HarnessFileRef) -> proto::FileRef {
    proto::FileRef {
        path: file.path.clone(),
        url: file.url.clone(),
        filename: file.filename.clone(),
        size_bytes: file.size_bytes,
    }
}

fn encode_repository(repository: &HarnessRepository) -> proto::RepoConfig {
    proto::RepoConfig {
        url: repository.url.clone(),
        branch: repository.branch.clone(),
        path: repository.path.clone(),
        authorization_token: String::new(),
        mount_name: repository.mount_name.clone(),
    }
}

#[cfg(test)]
mod tests {
    use crate::ids::TaskId;
    use crate::kernel::harness_contract::{
        HarnessFileMount, HarnessFileRef, HarnessInput, HarnessSkillArchive,
    };

    #[test]
    fn start_task_preserves_session_file_resources() {
        let input = HarnessInput {
            files: vec![HarnessFileMount {
                path: "/workspace/input.txt".to_string(),
                content: b"inline".to_vec(),
                filename: "input.txt".to_string(),
            }],
            file_refs: vec![HarnessFileRef {
                path: "/workspace/large.bin".to_string(),
                url: "https://files.example.test/large.bin".to_string(),
                filename: "large.bin".to_string(),
                size_bytes: 4096,
            }],
            ..Default::default()
        };

        let start = super::start_task(&input, TaskId::new(), 60);

        assert_eq!(start.files[0].path, input.files[0].path);
        assert_eq!(start.files[0].content, input.files[0].content);
        assert_eq!(start.file_refs[0].url, input.file_refs[0].url);
        assert_eq!(start.file_refs[0].size_bytes, input.file_refs[0].size_bytes);
    }

    #[test]
    fn skill_projection_is_owned_by_setup_only() {
        let input = HarnessInput {
            skills: vec![HarnessSkillArchive {
                name: "audit-skill".to_string(),
                tar_gz: b"archive".to_vec(),
                target: "skills".to_string(),
                skill_id: Some("skill_00000000-0000-0000-0000-000000000001".to_string()),
                skill_version: Some("1.2.3".to_string()),
                skill_version_id: Some("sklver_00000000-0000-0000-0000-000000000002".to_string()),
                skill_name: Some("audit-skill".to_string()),
                skill_source_type: Some("manual".to_string()),
                security_scan_id: Some("sklscan_00000000-0000-0000-0000-000000000003".to_string()),
                target_hash: Some("a".repeat(64)),
                artifact_hash: Some("b".repeat(64)),
            }],
            ..Default::default()
        };

        let setup = super::setup_sandbox(&input, "setup-1".to_string());
        let start = super::start_task(&input, TaskId::new(), 60);

        assert_eq!(setup.skills.len(), 1);
        assert_eq!(setup.skills[0].skill_id, input.skills[0].skill_id);
        assert_eq!(setup.skills[0].skill_version, input.skills[0].skill_version);
        assert_eq!(setup.skills[0].artifact_hash, input.skills[0].artifact_hash);
        assert_eq!(
            start.runtime_config_generation,
            input.runtime_config_generation
        );
    }
}
