# Port System — Dependency Inversion Architecture

## Principle

`core/` defines Protocol interfaces (Ports). `services/` provides implementations (Adapters). `core/` never imports from `services/`.

```
core/ports/           Protocol definitions (the contract)
services/*_adapter.py Concrete implementations (the wiring)
services/*_service.py Business logic (implements Port duck-typing)
```

## Port Catalog

### Fully Wired (injected at runtime)

| Port | File | Methods | Injected Via | Implementor |
|------|------|---------|-------------|-------------|
| `ExecutionEventPort` | `ports/execution.py` | mark_status, append_event, batch_append_events, complete_execution | Constructor (ExecutionRunner) | `execution_event_adapter.py` |
| `ExecutionReaderPort` | `ports/execution.py` | get_execution, get_run_for_execution, get_release_for_run, get_task_auto_approve, load_thread_history | Constructor (ExecutionRunner) | `execution_reader_adapter.py` |
| `ObservationCollectorPort` | `ports/observation.py` | start_span, start_agent, record_event, create_langchain_handler, finalize | `ExecutionContext.collector` | `ObservationCollector` |
| `ModelPort` | `ports/model.py` | get_model_instance, get_runtime_model_by_name | `ExecutionContext.model_port` | `ModelService` (duck type) |
| `ContextEventBridge` | `ports/context_event.py` | emit, update_status, complete | `ExecutionContext._event_bridge` | `launcher._Bridge` |
| `AgentSpawnPort` | `ports/agent_spawn.py` | spawn_and_wait, spawn_fire_and_forget, get_result | Parameter / module-level default | `agent_spawn_adapter.py` |
| `MemoryPort` | `ports/memory.py` | get_user_memories, upsert_user_memory, delete_user_memories, delete_user_memory, clear_memories | Constructor (MemoryManager) | `MemoryService` (duck type) |

### Defined with Fallback (transitional)

These Ports are defined and can be injected via optional parameters. When not injected, the consumer falls back to lazy-importing the service directly.

| Port | File | Consumer | Fallback |
|------|------|----------|----------|
| `SandboxPort` | `ports/sandbox.py` | `deep_agents/builder.py` | `sandbox_manager.get_sandbox_handle` |
| `SkillPort` | `ports/skill.py` | `deep_agents/skills_loader.py` | `SkillService(db)` |
| `McpServerPort` | `ports/mcp.py` | `tools/mcp_tool_utils.py` | `McpServerService(db)` |

### Remaining `core/` → `services/` References

| Location | Import | Category |
|----------|--------|----------|
| `engine/copilot_engine.py` | CopilotService | Self-contained subsystem |
| `copilot/agent.py` | ModelService | Self-contained subsystem |
| `scheduler.py` | DispatchService, ExecutionService | App-layer wiring |
| `graph/deep_agents/builder.py` | sandbox_manager | Fallback (SandboxPort ready) |
| `graph/deep_agents/skills_loader.py` | SkillService | Fallback (SkillPort ready) |
| `tools/mcp_tool_utils.py` | McpServerService | Fallback (McpServerPort ready) |

## Adding a New Port

1. Define Protocol in `core/ports/new_port.py`
2. Export from `core/ports/__init__.py`
3. Create adapter in `services/new_adapter.py`
4. Inject via ExecutionContext field, constructor parameter, or factory function
5. Update consumer to use Port instead of direct service import
