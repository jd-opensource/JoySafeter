use crate::grpc::{proto, tool_policy};
use crate::ids::TaskId;
use crate::kernel::harness_contract::{
    HarnessCustomTool, HarnessFileMount, HarnessFileRef, HarnessInput, HarnessMcpServer,
    HarnessMcpTransport, HarnessMemoryFile, HarnessMemoryStoreMount, HarnessRepository,
    HarnessSkillArchive,
};

pub(crate) fn setup_sandbox(input: &HarnessInput) -> proto::SetupSandbox {
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
        skills: input.skills.iter().map(encode_skill_archive).collect(),
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
    use crate::kernel::harness_contract::{HarnessFileMount, HarnessFileRef, HarnessInput};

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
}
