# Event/State Authority Stabilization

Date: 2026-07-21

## Objective

Stabilize the session execution loop without reducing production capability. The
first step is not a broad event-pipeline rewrite; it is to make the most critical
state/event boundary explicit and enforceable.

## Current Responsibility Split

- API owns user-facing validation, RBAC, idempotent user command ingestion, and
  task submission.
- Rust orchestrator owns scheduling, sandbox execution, runner gRPC, runtime
  control delivery, and runner-derived session state transitions.
- Worker owns Redis Stream consumption for non-status event persistence and
  replay-safe re-publication.
- PostgreSQL owns durable task/session state and canonical session event order.
- Redis owns wakeups, pub/sub fanout, command relay, and optional stream transport;
  it is not the scheduling or state authority.
- Frontend owns presentation and user commands; it treats REST/DB snapshots and
  canonical `seq` replay as authoritative.

## Phase 1 Boundary

Session status row changes and `session.status_*` event append are one logical
transition. In Rust gRPC execution and `TaskController` recovery/watchdog paths
they must be written by one helper:

- acquire the per-session advisory lock;
- update `joysafeter_sessions` with the status-machine guard;
- assign the canonical DB `seq`;
- insert the replayable `joysafeter_session_events` row;
- publish realtime only after the event row exists and has a canonical `seq`.
- mark already-persisted status envelopes so they do not re-enter the batch DB
  persister, state subscriber, or Redis fallback DB path.
- keep `session_seq` and `runner_seq` separate inside Rust event envelopes:
  `session_seq` is the canonical DB replay order, while `runner_seq` is only the
  runner-local harness order.
- make `flush_immediately` events persist synchronously before `EventBus::publish`
  returns; ordinary batched events still use fire-and-forget persistence.
- exclude all `session.status_*` events from the generic batch persister and
  Redis Stream persistence path. Status events are persisted only by the atomic
  status helper or by `SessionStateSubscriber`.

This phase deliberately does not change the API submission path, Redis Stream
topology, Worker batching policy, frontend state model, or RunSpec snapshotting.

## Phase 2 Boundary

For ordinary non-status session events, there must not be two primary DB writers
competing for the same canonical `seq`.

- When `JOYSAFETER_EVENT_STREAM_ENABLED=true`, Rust `EventBus` uses Redis Stream
  as the primary ordinary event persistence path; the Worker consumes and writes
  canonical DB rows.
- In that mode, Rust direct DB persistence is only a Redis-publish fallback when
  `JOYSAFETER_EVENT_STREAM_FALLBACK_TO_DB=true`.
- `flush_immediately` stream fallback must flush the direct DB persister before
  `EventBus::publish` returns.
- When Redis Stream is disabled, local/dev deployments keep Rust direct DB batch
  persistence as the primary path.
- Status events remain outside this generic path; they are owned by the atomic
  status helper or `SessionStateSubscriber`.

## Phase 3 Boundary

Queued execution must not be silently reinterpreted through mutable live agent or
environment rows after submission.

- API, session follow-up, and Worker schedule fires write a full
  `agent_snapshot` execution spec onto the session before enqueue.
- The snapshot includes agent model/system/env/tools/MCP/skills/permission mode,
  `environment_ref`, and the environment `config/image_tag/image_version`.
- Secret and vault values are not snapshotted as plaintext; the snapshot stores
  refs, and Rust resolves secret material at execution time through the existing
  secret/vault decrypt paths.
- Rust `HarnessInputBuilder`, `SandboxResolver`, sandbox credential recovery,
  and gRPC tool-event routing now interpret `session.agent_snapshot` first and
  fall back to live rows only for legacy sessions with incomplete snapshots.
- Pinned agent-version sessions use the pinned snapshot's environment unless the
  caller explicitly overrides the environment. The persisted session
  `environment_ref`, snapshot `environment_ref`, and embedded environment
  snapshot must remain consistent.

## Known Remaining Boundaries

- Rust gRPC and `TaskController` session status transitions now share the same
  atomic status/event helper.
- `events/session_state.rs`, `events/persist.rs`, and the Python Worker still all
  write session-event rows, but their authority is now separated by event
  category and runtime mode.
- Rust `EventPersister` now also rejects `session.status_*` events at the
  generic persister boundary itself, not only at `EventBus` and
  `EventStreamPublisher` call sites. Direct or accidental calls to the generic
  persister cannot append status events or consume canonical `seq`.
- Python Worker `EventBatchSender` rejects `session.status_*` events in both
  batched and single-write paths. Redis Stream consumer batches that contain a
  status event are acknowledged after the non-status events are durably handled,
  so skipped status events do not become poison messages.
- Control-event replay now treats `processed_at` as "sent to runner channel",
  not merely "attempted"; a failed replay send leaves the event pending for a
  future reconnect.
- Control events entering through the API normalize `evt_...` tool-use event
  ids to the runtime `_call_id` before persistence, Redis relay, or replay; the
  original event id is retained as `tool_use_event_id`.
- RunSpec snapshotting now covers agent/environment/tool/MCP/sandbox image and
  networking inputs. Vault contents, secret plaintext, memory-store contents,
  session files, and repo tokens still resolve live by reference at execution;
  that preserves current production capability and avoids storing plaintext in
  the RunSpec.
- Manual schedule triggers now use the same full execution snapshot builder as
  automatic schedule fires and `POST /tasks`; they no longer persist a shallow
  `{name, model}` snapshot that lets queued manual runs fall back to mutable
  live agent/environment rows.
- Rust scheduler legacy/repair auto-session creation now embeds the environment
  snapshot and writes the session `environment_ref`, rather than creating a
  session whose snapshot only contains agent-level fields.
- Rust scheduler auto-session creation now binds the new session to the task in
  the same transaction and only if the task is still `scheduling` with no
  existing `chat_session_id`. If a stale scheduler observation finds the task
  already moved out of `scheduling`, the transaction rolls back so no orphan
  auto-created session is leaked and the task is not mutated.
- Rust scheduler scheduling failures now compensate session state like dispatch
  failures: retryable failures move the task back to `pending`, release any
  attached sandbox, move the session to `rescheduling`, and append a persisted
  `session.status_rescheduling`; exhausted or non-retryable scheduler failures
  move the session back to `idle` with a persisted `session.status_idle`.
- Sandbox-controller bulk reset paths now use `UPDATE ... RETURNING` for
  scheduling-task recovery so session `rescheduling` repair is applied only to
  rows that were actually moved back to `pending`.
- Sandbox-controller and gRPC sandbox-cleanup bulk recovery now enforce
  `max_retries`: retryable scheduling tasks return to `pending` and move the
  session to `rescheduling`; exhausted scheduling tasks become `failed` and move
  the session to `idle` with a concrete error stop reason.
- gRPC orphan-task rescue now treats `running -> pending` retry as a visible
  session transition: after a successful task retry it persists and publishes a
  DB-sequenced `session.status_rescheduling` before relying on Redis/global
  queue re-enqueue.
- gRPC orphan-task rescue now also uses the same retry-exhaustion semantics as
  dispatch/failover. A running task already at retry limit is failed, the
  sandbox task association is released, and the session moves to `idle` instead
  of being requeued past its retry budget.
- SandboxResolver stopped-sandbox restart now claims the row with a guarded
  `stopped -> provisioning` write before calling `provider.start`. The claim is
  fenced on the observed external id; if start fails before dispatch, the row is
  restored to `stopped` only while it is still the same unbound provisioning row.
  If the DB row concurrently becomes `error`, `stopping`, or `destroyed`,
  resolver aborts scheduling and lets the existing scheduler compensation path
  run instead of resurrecting the sandbox back to `provisioning`.
- SandboxResolver new-sandbox creation now uses `creating -> provisioning` CAS.
  A CAS miss is accepted only when the same external sandbox is already active
  (`idle`, `running`, or `provisioning`), preserving fast runner-registration
  behavior without reviving terminal or cleanup states.
- After a new sandbox DB row exists, resolver no longer treats provisioning CAS
  failure as provider-create compensation. If that row concurrently changed to
  `error`, `stopping`, `stopped`, or another non-active state, resolver aborts
  without calling `provider.destroy`; the state owner or passive cleanup must
  drive any later external deletion.
- Provisioning progress/config updates now only write while the sandbox row is
  still in the expected status and not destroyed. A late provider progress poll
  can no longer move a sandbox that has concurrently become `error` or
  `destroyed` back to `provisioning`.
- Warm-pool claim metadata attachment now also requires the claimed row to
  still be `provisioning` or fast-runner-ready `idle`, unclaimed by any other
  session, and non-destroyed, preventing a stale claim from attaching a
  session/config payload to a concurrently cleaned-up pool row. If metadata
  attachment races with an `error` state, resolver aborts without moving the DB
  row out of `error` and without deleting a runtime it no longer proves it owns.
- Warm-pool ready/claim cleanup now uses a narrower DB ownership claim before
  provider destroy. Resolver may only delete the external runtime if the row is
  still an unattached `creating`/`provisioning` warm-pool row, has the same
  external id, and has no active task binding.
- Warm-pool stopped-runtime restart was verified to already follow the same
  ordering principle: `claim_pool_sandbox` moves the row out of reusable
  `pooled` state before `provider.start` runs, and metadata attach must then
  succeed on the claimed row before the sandbox is returned to scheduling.
- Warm-pool creation finalization now uses a dedicated guarded helper instead
  of an unconditional `status = 'pooled'` write. It accepts only unclaimed
  `creating`, `pooled`, or fast-runner-ready `idle` rows whose provisioning
  stage is `pool_warm`, and it preserves `error`/stop/destroy states. Rust and
  Python sandbox transition tables now both recognize `creating -> pooled`;
  generic `idle -> pooled` remains disallowed.
- Python sandbox idle expiry now uses `idle_since`, not stale `last_used_at`,
  matching the Rust sandbox controller and the model contract. A sandbox that
  just became idle after a long-running task is no longer immediately eligible
  for stop solely because `last_used_at` is old.
- gRPC dispatch start now binds `running + last_task_id` through one conditional
  DB update. A task can start only when the sandbox is still active
  (`idle`, `provisioning`, or the same `running` task); stale dispatch cannot
  revive `error`, `stopped`, `stopping`, or `destroyed` sandboxes.
- If the dispatch-start sandbox bind fails, gRPC uses the existing dispatch
  retry/failure compensation path before `StartTask`: retryable tasks return to
  `pending` and the session moves to `rescheduling`; exhausted tasks fail and
  the session returns to `idle`.
- gRPC task-completion, runner-idle, and reconnect-completion paths now reuse
  `complete_sandbox_task` instead of a raw `transition_sandbox(..., "idle")`.
  The sandbox task association is released on healthy sandboxes without moving
  concurrently errored/stopped/stopping/destroyed sandboxes back to `idle`.
- Deprecated Rust `transition_sandbox()` remains only as a compatibility
  wrapper and now enforces the sandbox state machine plus an observed-status
  `UPDATE` fence. Future accidental non-CAS callers cannot use it for invalid
  hops such as `error -> idle` or `creating -> running`, and stale callers lose
  races against concurrent terminal/error writes.
- Rust `mark_sandbox_error()` now refuses to clear a sandbox that still has a
  bound active task (`pending`, `scheduling`, or `running`). Setup-failure paths
  that own the active task first move that task terminal, then mark the sandbox
  `error`; late idle/setup-failure observations can no longer sever a live
  sandbox/task binding.
- SandboxController graceful idle-stop failure now reverts `stopping -> idle`
  with CAS only. If provider stop failure races with a setup/health path that
  marks the sandbox `error`, the controller no longer overwrites that error back
  to `idle`.
- SandboxController stop/force-stop paths now mark `stopped` through a helper
  that only updates active states and preserves `error`/`destroyed`. Provisioning
  provider-error and timeout paths now use `provisioning -> stopping` as the
  external-stop isolation state, repair scheduling tasks while the row is
  non-restartable, call `provider.stop`, then finalize `stopped` only if the row
  is still that `stopping` row.
- SandboxController force-stop for old `stopping` rows now re-runs DB
  task/session recovery before calling `provider.stop`, then re-claims the row
  with same external id and no active tasks. It finalizes `stopped` only while
  the row remains `stopping`, so force-stop cannot strand a running task or
  overwrite a row restored by another cleanup owner.
- SandboxController orphan cleanup now treats only non-`error`, non-`destroyed`,
  non-destroyed-at DB rows as owning a provider runtime. If a provider still has
  a live runtime for a DB row already marked `error` or `destroyed`, cleanup
  destroys the external runtime instead of skipping it as "known".
- SandboxController passive orphan cleanup now repairs tasks before destroying a
  DB sandbox row whose provider runtime is already missing. Retryable
  `scheduling` or `running` tasks are moved back to `pending`, their sessions
  are moved to `rescheduling`, and exhausted `running` tasks are failed with the
  session returned to `idle`.
- Missing-runtime task recovery treats Redis/global-queue notification as a
  best-effort wakeup, not the durable authority. The DB task/session repair is
  committed first; the scheduler's DB repair sweep remains the fallback if the
  Redis wakeup is unavailable or races with a consumer.
- SandboxController bridge health checks now use the same DB-authoritative
  missing-runtime recovery before marking the sandbox row destroyed. The
  in-memory bridge `current_task_id` is only a liveness hint; if it is already
  cleared while Postgres still has a `running` task, health cleanup repairs the
  task/session state instead of stranding the task.
- Bridge-health cleanup now treats `provider.destroy` as the external side
  effect, not the DB `destroyed` write. It repairs any DB-owned task first,
  claims the recovered sandbox row into `stopping` with external-id and
  active-task guards, then calls the provider and finalizes `destroyed`.
- SandboxController non-graceful disconnect/hard-timeout reaps now also repair
  DB task/session state before stopping the sandbox. Graceful idle stops keep
  the narrower scheduling-task reset, but reaps that can select `running`
  sandboxes use the same running/scheduling recovery path as missing-runtime and
  bridge-health cleanup.
- Non-graceful reaps now also re-claim the recovered sandbox row as `stopping`
  before bridge removal or `provider.stop`. This closes the window where task
  recovery had released a formerly `running` sandbox to `idle` while the
  external runtime was still about to be stopped; final `stopped` writes are
  fenced on `status = 'stopping'` and the observed external id.
- Passive sandbox destroy writes are now split from explicit force-destroy
  commands. Stopped/error TTL cleanup and stale warm-pool cleanup mark
  `destroyed` only when the row still matches the status and external id
  observed before the provider call, so a stale sweep cannot overwrite a
  sandbox that concurrently restarted or moved back into provisioning.
- Explicit Redis destroy commands are now fenced separately from passive
  cleanup. The command listener first proves the DB row still matches the
  command's `external_id`, claims it as `stopping`, then calls
  `provider.destroy` and finalizes `destroyed` with the same external-id fence.
  A stale command whose `external_id` no longer matches the row fails before
  any provider call or DB destroy, while duplicate commands against an already
  destroyed matching row remain idempotent.
- Python API/project/agent post-ACK sandbox state sync now uses the same
  command external-id fence. After Redis destroy ACK, Python may idempotently
  mark the row `destroyed` only if both the observed status and observed
  external id still match, or if Rust already finalized the same external id as
  `destroyed`. It no longer falls back to broad `mark_destroyed()` or ignores a
  failed CAS while deleting/archiving the parent resource.
- Python task cancellation post-ACK state sync now fences the DB cancel on the
  observed task `sandbox_id` and `owner_epoch`. A Redis cancel ACK only proves
  the command reached the previously observed runtime owner; if the task is
  concurrently reassigned to another sandbox/epoch before DB finalization, the
  API raises `TASK_CANCEL_STATE_SYNC_FAILED` and leaves the task/session state
  unchanged.
- Passive sandbox cleanup now treats provider/runtime deletion as a downstream
  side effect that must not run until Postgres ownership has been re-proven.
  Resolver stale-sandbox cleanup and controller stopped/error or stale-pool
  cleanup first claim the row into `stopping` with observed status, external id,
  and active-task guards; only then do they call `provider.destroy`, and only
  after successful provider deletion do they finalize the row as `destroyed`.
- If provider destruction fails during a passive cleanup claim, the row is
  restored from `stopping` back to the previously observed status instead of
  being hidden as `destroyed` while an external runtime may still exist.
- Missing-runtime cleanup now uses a recovery-aware destroy guard after task
  repair. Bridge-health cleanup uses the same recovered-row eligibility before
  provider deletion, but first claims the row as `stopping` so the external
  deletion cannot race with scheduler reuse. Both paths require the same
  external id and no active `pending`/`scheduling`/`running` task before the row
  can be marked destroyed.
- gRPC dispatch retry compensation now carries the optional scheduler queue
  explicitly through `handle_dispatch_retryable_failure`. Production
  `StartTask` send failures can re-enqueue retryable tasks through the same
  helper, while tests and orphan-rescue paths that already own their requeue
  step pass `None` to avoid duplicate enqueue semantics.
- Uploaded file deletion is rejected while the file is still attached to any
  non-archived, non-terminated session resource; users must remove the resource
  first so already-created sessions do not silently lose mounted files.
- Rust harness input construction now treats declared session resource load
  failures as execution-preparation failures. Missing file storage content,
  memory DB read failures, or undecryptable repo tokens no longer degrade into
  a task that runs without the declared resource.
- Rust gRPC dispatch now preserves that contract at the `StartTask` boundary.
  If `HarnessInputBuilder` fails, dispatch marks the task failed and returns the
  sandbox to idle instead of fabricating a minimal `StartTask` with empty
  files/repos/memory/secrets.
- Rust gRPC pre-`StartTask` failures now also compensate the session state.
  Agent-not-found, setup-send, session-file injection, or harness-input build
  failures mark the task failed, clear the sandbox task association, and append
  a persisted `session.status_idle` event when the API had already marked the
  session running.
- Rust gRPC pre-`StartTask` and dispatch failure helpers now release sandbox
  ownership only after the task retry/failure mutation succeeds. A stale
  pre-start, start-send, or failover observation that loses to an already
  terminal task no longer clears sandbox `last_task_id` or writes a false
  `session.status_*` event.
- Terminal/recovery session status repairs now have an additional
  transaction-local active-task guard. `idle`/`terminated` repairs from cleanup,
  watchdog, scheduler, and terminal task paths only update the session row and
  append the status event when no task in that session remains `pending`,
  `scheduling`, or `running`.
- Non-DB-persisted raw `session.status_idle`/`session.status_terminated` events
  handled by `SessionStateSubscriber` use the same active-task guard. The
  `requires_action` idle state remains explicitly allowed while its task is
  still running, preserving HITL behavior while rejecting stale `end_turn` idle
  events.
- gRPC delayed sandbox cleanup no longer turns a session idle just because an
  old sandbox disappears. A cleanup callback for an already-destroyed/replaced
  sandbox skips `sandbox_disconnected` idle repair when the same session has an
  active task on another sandbox.
- Python `SessionService.update_session_status` now has an optional
  transaction-local active-task guard, and session stop/archive use it for
  non-task-scoped `idle`/`terminated` repairs. A task appearing after the
  route-level active-task recheck but before the final idle write causes
  `stop_session` to fail closed instead of reporting the session idle.
- Agent and project archive paths now also fail closed when an active task
  appears after their initial active-task precheck. Agent session archival uses
  a guarded bulk update that refuses to terminate any session with a non-terminal
  task; project archival performs a second session-scoped active-task check
  before sandbox cleanup and keeps the final session archival update guarded.
- Runtime retry/failure compensation now uses a `running`-scoped retry CAS and
  `running -> failed` CAS. Late dispatch/failover observations can no longer
  increment retry count, fail, or write session status for tasks that have
  already been returned to `pending`; the old broad non-terminal retry and task
  transition helpers were removed to prevent future reuse.
- Sandbox file injection now follows the same contract as harness input
  construction. Missing session-file storage content, invalid mount paths, or
  provider upload failures fail sandbox preparation instead of logging a warning
  and continuing with an incomplete workspace.
- `SetupSandbox` delivery is now an observable prerequisite. A setup send is
  marked done only after a message is actually accepted by the runner channel;
  a session-linked task fails before `StartTask` if setup cannot be sent.
- Runner memory sync now re-checks `joysafeter_memory_stores.archived_at` under
  `FOR UPDATE` before modifying/deleting memory files. API/Service already reject
  ordinary writes to archived stores; this closes the direct Rust DB write path
  without changing readable archived history.
- Session memory-store attachment now has the same Service-layer mutation guard
  as file/repo resources. Direct calls to `SessionService.attach_memory_stores`
  reject archived, terminated, rescheduling, or non-idle sessions, and reject
  archived memory stores before creating any mount row.
- Memory-store attachment now validates the whole requested batch before adding
  any mount rows. Duplicate store ids and already-attached stores return a
  structured conflict instead of relying on the DB unique constraint or leaving
  earlier rows pending through SQLAlchemy autoflush.
- Session file resources now reject duplicate normalized `mount_path` values in
  both `POST /sessions` batches and direct Service additions. This prevents Rust
  harness input and sandbox file injection from receiving two different files
  for the same workspace path and depending on ambiguous last-writer behavior.
- Session repo resources now reject duplicate effective clone destinations in
  both `POST /sessions` batches and direct Service additions. Effective
  destinations match runner semantics: explicit `mount_path` if provided, or
  `/workspace/<repo-name-from-url>` when omitted.
- Runner repo cloning now treats declared repo resources as required setup
  inputs. A clone failure in `SetupSandbox` or the `StartTask` fallback returns
  an error instead of logging a warning and starting the agent without the repo.
- Runner setup commands now follow the same required-input contract. A non-zero
  command in `SetupSandbox` or the `StartTask` fallback aborts setup before the
  agent starts and prevents later setup commands from running against a broken
  workspace.
- `StartTask` preflight failures now emit a failed `RunnerHarnessResult` with
  task session/work_dir context instead of only logging and returning
  `RunnerIdle`. Surviving tasks retain that context across reconnect so a
  pre-agent failure is still observable after the gRPC stream is restored.
- Runner initial memory-file materialization is now required when FUSE is not
  active. Directory creation or file writes for declared memory mounts fail
  sandbox setup instead of logging a warning and starting with missing seed
  memory files.
- Runner file-ref downloads now treat non-success HTTP status as setup failure.
  A presigned URL that returns 4xx/5xx no longer lets setup complete without the
  declared file.
- Runner auto-extraction of recognized archive file resources is now required.
  If an inline `FileMount` or downloaded `FileRef` has an archive suffix but
  cannot be extracted, sandbox setup fails instead of starting with only the raw
  broken archive present.
- `SetupSandbox` runner-side failures are now observable by the orchestrator.
  The runner emits a failed `RunnerHarnessResult` with a `SetupSandbox failed`
  prefix; the orchestrator recognizes that result while idle, clears
  `setup_done`, and marks the sandbox `error` with `config.setup_error`.
- If a `SetupSandbox` failure result arrives while a task is already in the
  dispatch loop, it is not treated as an ordinary task failure that returns the
  sandbox to `idle`. The task is failed, the session returns to `idle` with the
  setup error stop reason, and the sandbox remains `error` so it is ejected.
- Task CAS terminal transitions now stamp `completed_at` and `duration_ms`.
  Timeout and cancellation paths can legitimately move `running` tasks directly
  to terminal states without a later runner `complete_task` write; those tasks
  now keep the same completion metadata contract as ordinary result/failure
  paths.
- Rust gRPC cancellation, timeout, runner-result, runner-idle, and post-result
  fallback paths now separate task-terminal authority from session-idle
  publication. A `session.status_idle` event is published only after the task
  terminal CAS succeeds, or after the DB already shows an authoritative terminal
  state; late runner results after cancellation no longer rewrite the cancelled
  session stop reason to `end_turn`.
- Rust gRPC stream-close/stream-error paths before a runner result now route
  through the same failover compensation path as heartbeat disconnects. They no
  longer directly mark the task failed while leaving retry budget, sandbox
  release, and session `rescheduling`/`idle` compensation to chance.
- Failover paths that detect already-streamed `agent.message` output now treat
  completion as a real terminal transition. gRPC and `TaskController` only write
  `session.status_idle(end_turn)` after the task successfully moves to
  `completed`, and they release the sandbox task association on that successful
  completion. That completion is now explicitly `running -> completed`; a task
  already retried back to `pending` cannot be completed by a late failover path
  solely because an earlier attempt emitted `agent.message`.
- `TaskController` retry/failure helpers now release sandbox ownership only
  after their task mutation succeeds. A stale retry or failover observation that
  loses to an already-terminal task no longer clears sandbox `last_task_id` or
  writes a false session status event.
- `TaskController` overdue-task watchdog now uses `running -> timeout` CAS and
  releases the sandbox task association only after that CAS succeeds. A stale
  watchdog observation can no longer timeout a task that another path already
  moved out of `running`, and normal watchdog timeouts no longer leave the
  sandbox pinned to a terminal task.
- `TaskController` startup scheduling recovery and stuck-scheduling watchdog now
  use scheduling-scoped task CAS helpers. They retry or fail only rows that are
  still in `scheduling`, and release sandbox/session state only after the task
  mutation succeeds; stale observations no longer move already-running tasks
  back to `pending`, mark them failed, or clear their sandbox ownership.
- Scheduler failure compensation is now explicitly `scheduling`-scoped.
  Resolver/semaphore failure callbacks can retry, fail, or cancel only tasks
  that are still in `scheduling`; late scheduler observations can no longer move
  a task that already reached `running` back to `pending` or terminal.
- Session repo resources are session-local rows (`joysafeter_session_repos`), so
  there is no separate global repo deletion path like files. The relevant
  boundary is resource mutation while a session is non-idle: Service-layer add,
  delete, and token rotation now enforce the same mutable-session guard as the
  API, preserving the existing cross-project "resource not found" hiding
  semantics for child rows.
- Vault references are durable session inputs but secret plaintext must remain
  live-resolved. The API accepts both `vault_...` and `vlt_...`; Rust harness
  and sandbox credential resolution now parse both aliases. Vault delete/archive
  is rejected while the vault is referenced by any non-archived, non-terminated
  session, so a later run does not silently lose MCP credentials.
- A future schema-level command state can still split `queued/sent/acked`, but
  the current guard prevents silent loss without a migration.

## Production Guardrails

- Keep task claim, sandbox execution, cancellation relay, and SSE replay behavior
  unchanged.
- Do not publish raw status events from Rust gRPC when DB did not accept and
  sequence the corresponding status event.
- Do not treat runner-provided `seq` as canonical session `seq` for UI status
  broadcasts.
- Keep duplicate running/idle events suppressed by the existing status transition
  guard rather than frontend filtering.
- Keep non-status event redelivery idempotent without consuming canonical DB
  `seq`; a duplicate `event_id` must not create replay gaps for later events.
- Do not run `EventStreamPublisher` as a broadcast subscriber when `EventBus`
  already owns stream publishing; that recreates duplicate XADD paths.
- Do not allow any generic event persister or Worker fallback path to append
  `session.status_*`; status row/event authority must stay with the atomic
  helper or `SessionStateSubscriber`.
- Do not set `processed_at` for pending control replay unless
  `OrchestratorMessage::Input` was accepted by the runner channel.
- Do not send a user-facing `evt_...` control request id to the runner protocol;
  runner live input must use the runtime call id while DB payload keeps the
  user-facing event id for audit/replay context.
- Do not let live agent/environment edits change the model/system/env/tools,
  sandbox image, networking policy, or environment package commands for an
  already-submitted session/task.
- Do not let stale provisioning or restart observations overwrite terminal
  sandbox states. `error`, `stopping`, and `destroyed` must stay authoritative
  unless an explicit cleanup path moves them further toward destruction.
- Do not call `provider.start` for a stopped sandbox before Postgres has claimed
  the row into `provisioning` with the same external id. A post-start CAS miss
  is too late; the external runtime may already have been started for a row now
  owned by an error/cleanup path.
- Do not use `last_used_at` as the clean-idle sweep authority. It is touched by
  liveness/heartbeat paths; clean idle expiry must use `idle_since`.
- Do not let manual schedule trigger sessions regress to a shallow agent
  snapshot; they must capture the same execution spec shape as automatic
  schedule fires before enqueue.
- Do not let Rust DB-repair or legacy pending-task paths auto-create sessions
  with a partial snapshot or missing session `environment_ref`; these sessions
  must preserve the environment config/image used at scheduler claim time.
- Do not retry or fail a scheduler-owned task while leaving its session stuck in
  the prior `running`/`rescheduling` state. Scheduler retry/failure is a
  user-visible execution-state transition, not only a task-row mutation.
- Do not bulk-reset sandbox-attached scheduling tasks without knowing the exact
  changed rows. Session repair and requeue should be based on returned task ids,
  not a separate pre-read that can race with task ownership changes.
- Do not rescue orphaned running tasks by mutating only the task row. Even if
  Redis requeue later fails, DB/replay must already show the session as
  `rescheduling` for the retried task.
- Do not let sandbox health/provisioning cleanup or reconnect rescue bypass
  `max_retries`. Recovery is a task failure path and must either retry within
  budget or fail visibly with a persisted idle status event.
- Do not destroy a DB sandbox row for a missing provider runtime while leaving
  its bound `scheduling` or `running` task stranded. Passive cleanup must first
  either retry the task within budget with a persisted `rescheduling` status, or
  fail it visibly at retry exhaustion.
- Do not make Redis queue delivery the commit authority for task recovery.
  Redis can wake the scheduler, but the committed Postgres `pending` task row is
  the durable recovery record and must remain recoverable by DB sweep.
- Do not use in-memory bridge task state as the only cleanup authority. Bridge
  health checks run asynchronously against task completion/failover paths, so
  they must re-check and repair Postgres `scheduling`/`running` tasks, then
  claim the row in Postgres before calling provider destroy or marking the
  sandbox row destroyed.
- Do not let disconnect or hard-timeout sandbox reaping stop a `running`
  sandbox while mutating only scheduling tasks. Non-graceful reaps are runtime
  loss/failover paths and must retry or fail DB-running tasks before the sandbox
  is stopped.
- Do not call `provider.stop` for a passively recovered running sandbox while
  Postgres shows the row as reusable `idle`. After recovery, the controller must
  first prove same external id, no active task, and move the row to `stopping`;
  if that claim fails, skip the downstream provider stop.
- Do not expose provisioning cleanup as `stopped` before `provider.stop`
  completes. `stopped` is restartable by `SandboxResolver`; timeout/provider
  error cleanup must use `stopping` while the external runtime is being stopped.
- Do not treat a stale `stopping` row as proof that provider stop is safe.
  Force-stop must first repair any bound scheduling/running tasks, then re-prove
  same external id plus no active task before the downstream stop call.
- Do not use the broad `destroy_sandbox()` helper from passive cleanup paths.
  Passive cleanup must either prove the row still matches the observed
  status/external id, or after task recovery prove no active task remains and
  the external id did not change. Explicit command-listener/admin destruction
  remains the separate force-destroy path, but it still must claim the row with
  the command's external id before any provider-side deletion.
- Do not treat Redis destroy ACK as permission for a status-only Python DB
  overwrite. The ACK proves the runtime side accepted a command for a specific
  external id; Python post-ACK state sync must fence on that same external id
  and fail closed if the row was already reused or replaced.
- Do not treat Redis cancel ACK as permission for a task-id-only DB cancel. The
  ACK is scoped to the observed sandbox runtime owner; DB finalization must
  still prove the task row has the same `sandbox_id` and `owner_epoch` before
  marking it `cancelled` or idling the session.
- When diagnosing cleanup bugs, first classify the failed observation as
  upstream input drift, local stale observation, or downstream side effect. A
  provider destroy call is downstream and must be gated by a DB ownership claim;
  an after-the-fact DB CAS alone does not prevent killing a runtime that another
  path has already made active.
- Provider-create compensation is only valid before a durable DB sandbox row
  exists. Once `create_sandbox` has inserted the row, later CAS failure is a DB
  ownership conflict, not a license to delete the external runtime directly.
- Do not snapshot decrypted secret values into `agent_snapshot`.
- Do not allow global file deletion to make an existing session resource
  disappear from Rust file injection; either remove the session resource first
  or terminate/archive the session.
- Do not continue harness execution after a declared session file, memory store,
  or repo credential fails to load; failing before runner start is preferable to
  silently executing against incomplete inputs.
- Do not recover from Rust `HarnessInputBuilder` errors by constructing a
  minimal `StartTask`. That path discards declared resources and bypasses the
  fail-closed checks in harness input construction.
- Do not publish timeout/cancel/result-derived `session.status_idle` from Rust
  gRPC when the corresponding task terminal CAS did not succeed. If the task is
  already terminal, the DB terminal state remains authoritative for the session
  result; late runner messages must not overwrite the existing stop reason.
- Do not handle runner stream close/error before result by mutating only the task
  row. A disconnect is a failover path: it must either retry within budget with
  a persisted `session.status_rescheduling`, or fail visibly at retry exhaustion.
- Do not use presence of `agent.message` output as permission to publish
  `end_turn` unless the task completion transition succeeded. Otherwise a stale
  failover observation can overwrite a concurrent terminal stop reason.
- Do not let timeout watchdogs use a broad non-terminal task transition. Timeout
  detection starts from a stale read by definition; the write must prove the task
  is still `running` before publishing session idle or releasing the sandbox.
- Do not let scheduler failure callbacks use broad non-terminal task
  transitions. A scheduler error is authoritative only while the task remains
  `scheduling`; after sandbox claim/runner start, runtime failover owns the
  task/session compensation.
- Do not fail a pre-`StartTask` task while leaving its session in `running`.
  The API submission path already emitted `session.status_running`; dispatch
  preparation failures must publish the matching `session.status_idle` event so
  UI/replay and DB state converge.
- Do not continue sandbox preparation after declared session-file injection
  fails. Warm-pool claims that cannot receive their session files are destroyed
  rather than reused as silently incomplete workspaces.
- Do not treat warm-pool ready finalization or attach failure as permission to
  destroy the provider runtime. First prove the row is still an unattached
  warm-pool `creating`/`provisioning` row; if a concurrent `error`, session
  attach, or task binding won, skip external destroy and let that owner drive
  cleanup.
- Do not mark `bridge.setup_done` when `SetupSandbox` was skipped, failed to
  build, or failed to send. For session-linked tasks, setup failure must fail the
  task before `StartTask` is sent.
- Do not treat accepting a `SetupSandbox` message on the runner channel as proof
  that sandbox setup succeeded. Runner-side setup failures must be reported back
  and must remove that sandbox from the healthy scheduling pool.
- Do not route a task-phase `SetupSandbox failed` result through the ordinary
  `complete_sandbox_task` path; that path clears `last_task_id` and returns the
  sandbox to `idle`, which would keep an incompletely prepared sandbox available.
- Do not let runner-originated memory sync mutate an archived memory store, even
  if a stale runtime still has a mounted `session_memory_store` row.
- Do not rely on session creation route checks as the only guard for memory-store
  attachment; the direct Service method must reject non-idle sessions and
  archived stores before creating `joysafeter_session_memory_stores` rows.
- Do not allow a partially valid memory-store attach batch to create earlier
  mounts when a later store is archived, missing, or duplicate.
- Do not allow duplicate session file mount paths. Path normalization must happen
  before conflict checks so `/workspace/./x` and `/workspace/x` cannot coexist.
- Do not allow duplicate repo effective clone destinations. Empty repo
  `mount_path` must be compared using the same URL-derived default path that the
  runner uses, otherwise two rows can collide at clone time while appearing
  distinct in the API.
- Do not let runner repo clone failures silently degrade into an incomplete
  workspace. Repo resources are declared inputs like session files; failing
  before agent start is preferable to running against a missing checkout.
- Do not treat runner setup command failures as warnings. The first failed
  command must abort setup/task fallback and must not allow the agent or later
  setup commands to run against a partially prepared workspace.
- Do not convert a runner `handle_task` preflight error into plain `RunnerIdle`;
  task dispatch needs a failed `RunnerHarnessResult` first so the orchestrator
  can complete the task as failed instead of waiting for a result that never
  arrives.
- Do not continue sandbox setup after declared initial memory files cannot be
  materialized. Missing seed memory is an incomplete declared workspace, not a
  recoverable cosmetic warning.
- Do not continue sandbox setup after a declared file-ref presigned download
  returns a non-success HTTP status. The task should fail before agent start
  rather than run without the uploaded file.
- Do not treat recognized archive auto-extraction failures as cosmetic. The
  runner already chooses to auto-extract by suffix; failure means the workspace
  contents implied by that file resource were not materialized.
- Do not rely on API route pre-checks as the only guard for session resource
  mutation; Service methods must reject direct add/delete/repo-token rotation
  for archived, terminated, rescheduling, or non-idle sessions.
- Do not rely on a pre-archive active-task count as permission to terminate all
  agent/project sessions. The archival write itself must prove no non-terminal
  task is attached to the target sessions.
- Do not snapshot decrypted vault credential values; do normalize/accept all API
  supported vault id aliases at every runtime credential resolution boundary.
- Do not delete or archive a vault still referenced by resumable sessions; token
  updates remain allowed so credential rotation does not require session
  teardown.
- Validate with `cargo check`, static Rust status-event contract tests, and real
  Postgres scenario tests for canonical seq assignment, duplicate suppression,
  transaction rollback, db-persisted EventBus bypass, and RunSpec snapshot
  execution after live config mutation.

## Real Scenario Coverage

- `atomic_session_status_helper_writes_status_event_and_canonical_seq` creates a
  real agent/session, runs `idle -> running -> idle`, and verifies the session
  row, persisted status events, canonical `seq`, and duplicate running no-op.
- `atomic_session_status_helper_rolls_back_status_when_seq_assignment_fails`
  forces a DB error after the status update step and verifies the transaction
  rolls the session row back to `idle` with no `session.status_running` event.
- `db_persisted_status_envelope_does_not_reenter_event_bus_db_persister` publishes
  a DB-persisted status envelope through `EventBus` and verifies the DB still has
  exactly the original status event.
- `event_bus_persists_runner_event_with_canonical_db_seq_not_runner_seq` publishes
  a normal runner event with `runner_seq = 777` through `EventBus` and verifies
  the persisted DB event uses canonical `seq = 1`. This scenario also guards
  `flush_immediately`: the event must be durably visible when `publish` returns.
- `event_persister_redelivered_event_id_does_not_consume_next_db_seq` persists
  an event, flushes it, then redelivers the same `event_id` followed by a
  distinct event through Rust `EventPersister` and verifies Postgres contains
  only two rows with canonical `seq = 1, 2`.
- `event_persister_skips_session_status_events_even_when_called_directly` calls
  Rust `EventPersister` directly with a `session.status_idle` event followed by
  `agent.message`, then verifies only the non-status row is persisted with
  `seq = 1` and the session row remains `running`.
- `event_bus_stream_primary_falls_back_to_db_before_flush_immediate_returns`
  enables Redis Stream mode, points Redis at an unavailable endpoint, and
  verifies a `flush_immediately` event is synchronously persisted by DB fallback.
- `event_bus_stream_primary_without_fallback_does_not_direct_write_to_db`
  enables Redis Stream mode with fallback disabled, points Redis at an
  unavailable endpoint, and verifies Rust does not silently use direct DB as a
  second primary writer.
- `pending_control_replay_marks_processed_only_after_send_succeeds` creates a
  real pending control-event set in Postgres, verifies a closed runner channel
  leaves `processed_at` null, then verifies successful replay sends structured
  `tool_confirmation`, `custom_tool_result`, and `interrupt` live-input payloads
  and marks the rows processed.
- `test_tool_confirmation_event_id_is_resolved_to_runtime_call_id_for_redis_relay`
  and `test_custom_tool_result_event_id_is_resolved_to_runtime_call_id_for_redis_relay`
  create real control-request events, submit user responses with `evt_...`
  ids, and verify API persistence plus Redis relay use the runtime call id.
- `raw_status_envelope_through_subscriber_uses_canonical_db_seq_not_runner_seq`
  sends a raw runner status envelope through `SessionStateSubscriber` and verifies
  it persists with canonical DB `seq = 1`, not runner `seq = 777`.
- `event_bus_routes_raw_status_to_state_subscriber_not_generic_persister` sends a
  raw status envelope through `EventBus` and verifies the status row/event are
  written by the state subscriber path with canonical DB `seq = 1`.
- `stream_publisher_skips_status_events_instead_of_falling_back_to_db` sends a
  status envelope to the Redis Stream publisher with DB fallback enabled and
  verifies neither session row nor session event is written by that path.
- `test_stream_consumer_acks_status_events_without_persisting_them` feeds the
  Python Redis Stream consumer a mixed status/non-status batch, verifies the
  status event is not written and does not mutate `joysafeter_sessions`, verifies
  the non-status event persists with canonical `seq = 1`, and verifies both
  stream message ids are acknowledged.
- Redis Stream publishing preserves both meanings explicitly: legacy `seq` and
  `session_seq` carry the DB sequence when known, while `runner_seq` carries the
  runner-local harness sequence for diagnostics only.
- `tests/test_rust_session_status_real_scenarios.py` invokes these Rust scenario
  tests from pytest using the migrated Postgres fixture, so normal backend
  integration test runs exercise the real database path.
- `harness_input_uses_session_execution_snapshot_after_live_config_changes`
  creates real agent/environment/secret/session/task rows, mutates live config,
  and verifies Rust harness input still uses the submitted snapshot for model,
  system prompt, env vars, setup commands, MCP, custom tools, and secret refs.
- `sandbox_resolver_uses_session_snapshot_for_image_network_and_env` resolves a
  real sandbox through a recording provider and verifies image, network mode,
  env fingerprint, and provider create config come from the session snapshot,
  not mutated live rows.
- `sandbox_resolver_restart_does_not_resurrect_concurrent_error` creates a real
  stopped session sandbox, simulates provider restart racing with a DB
  `error` transition, and verifies resolver aborts instead of moving the row
  back to `provisioning`.
- `sandbox_resolver_restart_claims_row_before_provider_start` creates a real
  stopped session sandbox, records DB status inside `provider.start`, and
  verifies the provider call only runs after the row is already claimed as
  `provisioning`.
- `provisioning_progress_update_does_not_resurrect_error_sandbox` creates a
  real sandbox row, marks it `error`, then verifies a late provisioning progress
  update is rejected and the original error/config remain authoritative.
- `start_sandbox_task_binds_healthy_sandbox_to_task` creates real
  agent/session/task/sandbox rows and verifies dispatch-start atomically moves a
  healthy idle sandbox to `running`, binds `last_task_id`, and clears
  `idle_since`.
- `start_sandbox_task_does_not_resurrect_error_sandbox` creates real
  agent/session/task/sandbox rows, marks the sandbox `error`, and verifies
  dispatch-start returns false without changing status, `last_task_id`, or the
  recorded setup error.
- `transition_sandbox_rejects_invalid_error_to_idle_resurrection` creates a
  real sandbox row, marks it `error`, calls the deprecated compatibility helper
  toward `idle`, and verifies the helper returns false while preserving the
  original `error` status and `config.setup_error`.
- `mark_sandbox_error_does_not_clear_active_task_binding` creates real
  session/task/sandbox rows with a running task bound to the sandbox, then
  verifies a late sandbox-error write is rejected without clearing
  `last_task_id`, changing task ownership, or recording a stale setup error.
- `scheduling_retry_helpers_do_not_move_running_tasks_back_to_pending` creates
  real scheduling and running task rows, verifies scheduling reset returns only
  the scheduling row to `pending`, and verifies scheduling retry/reset helpers
  leave the running row and retry count unchanged.
- `graceful_stop_failure_does_not_revert_concurrent_error_to_idle` creates a
  real idle sandbox, simulates provider stop failure racing with a DB `error`
  transition, and verifies the controller does not move the row back to `idle`.
- `mark_sandbox_stopped_if_active_stops_running_sandbox` creates real
  agent/session/task/sandbox rows and verifies the stop helper moves a running
  sandbox to `stopped` without clearing the task association.
- `mark_sandbox_stopped_if_active_does_not_overwrite_error_sandbox` creates a
  real sandbox row, marks it `error`, then verifies a stale stop write is
  rejected and the error details remain authoritative.
- `test_idle_expiry_uses_idle_since_not_stale_last_used_at` creates a real
  sandbox with stale `last_used_at`, transitions it to `idle`, and verifies the
  Python idle-expiry query does not select it until `idle_since` ages out.
- `test_sandbox_state_machine_allows_provisioning_to_stopping_for_cleanup`
  verifies the Python sandbox state machine accepts the same
  `provisioning -> stopping` cleanup isolation transition used by Rust.
- `test_idle_expiry_selects_rows_by_idle_since` creates a real idle sandbox with
  fresh `last_used_at` but stale `idle_since`, then verifies Python idle expiry
  selects it by the authoritative clean-idle timestamp.
- `test_archive_agent_fails_closed_when_task_appears_after_active_check` creates
  real agent/session rows, injects a pending task after the archive precheck,
  and verifies the API returns the existing active-task conflict while leaving
  the agent/session unarchived.
- `test_archive_project_fails_closed_when_task_appears_after_active_check`
  creates real project/agent/session rows, injects a pending task after the
  project archive precheck, and verifies the project/session remain unarchived
  with the standard project active-task conflict.
- `test_create_session_pinned_agent_version_uses_snapshot_environment` verifies
  the API persists a pinned agent-version session with the pinned environment
  ref and embedded environment snapshot.
- `test_create_task_auto_session_stores_execution_snapshot` verifies `POST
  /tasks` auto-created sessions persist the submitted agent/environment snapshot
  before later live config changes.
- `test_manual_schedule_trigger_stores_full_execution_snapshot` creates real
  project/agent/environment/schedule/session/task rows through the manual
  schedule trigger path, verifies Redis enqueue, verifies the persisted session
  snapshot contains model, system prompt, env, MCP, tools, environment config,
  image tag, and image version, then mutates live agent/environment rows and
  verifies the submitted session snapshot does not drift.
- `scheduler_auto_session_snapshot_includes_environment_before_live_mutation`
  creates real Rust DB agent/environment/session rows through the scheduler
  auto-session helper, verifies session `environment_ref` plus embedded
  environment config/image tag/image version, then mutates live rows and
  verifies the submitted snapshot remains stable.
- `scheduler_auto_session_attach_skips_task_that_left_scheduling_without_leaking_session`
  creates a real no-session task that has already left `scheduling`, exercises
  the scheduler auto-session path, and verifies the task remains unchanged and
  no auto-created session row is leaked.
- `scheduler_failure_retry_marks_session_rescheduling_and_releases_sandbox`
  creates real running session/task/sandbox rows, exercises the scheduler
  failure handler within retry budget, and verifies the task returns to
  `pending`, the sandbox is released, the session moves to `rescheduling`, and
  a matching `session.status_rescheduling` event is persisted.
  The test uses an intentionally unreachable Redis endpoint so committed DB
  retry state is not raced by a live local Redis consumer on port 6379.
- `scheduler_failure_ignores_task_that_already_left_scheduling` creates a real
  session/task/sandbox row where the task is already `running`, then exercises a
  late scheduler failure callback and verifies task status, retry count, sandbox
  ownership, session status, and session events remain unchanged.
- `scheduler_failure_exhausted_marks_session_idle` creates a real
  `rescheduling` session with a scheduling task at retry limit, exercises the
  scheduler failure handler, and verifies the task becomes `failed`, the session
  moves to `idle`, and the persisted idle event carries the concrete resolver
  failure reason.
- `scheduler_deleted_agent_marks_existing_session_idle` creates a real
  soft-deleted agent with an existing running session/task and verifies the
  scheduler's agent-resolution failure path marks the task failed and moves the
  session back to `idle` with an error stop reason.
- `scheduler_archived_agent_cancels_task_and_idles_session` creates a real
  archived agent with an existing running session/task and verifies scheduler
  cancellation moves the task to `cancelled` and the session to `idle` with a
  persisted cancelled stop reason.
- `sandbox_bulk_reset_marks_session_rescheduling_event` creates real
  session/task/sandbox rows in `running`/`scheduling` state, exercises the
  sandbox-controller bulk reset query plus session repair helper, and verifies
  the task returns to `pending`, retry count increments, sandbox ownership is
  cleared, the session moves to `rescheduling`, and a matching status event is
  persisted.
- `sandbox_bulk_reset_exhausted_marks_task_failed_and_session_idle` creates real
  `rescheduling` session/task/sandbox rows with the task already at retry limit,
  exercises the exhausted bulk-recovery query plus session repair helper, and
  verifies no pending retry is created, the task becomes `failed`, and the
  session moves to `idle` with a matching status event.
- `cleanup_orphaned_missing_runtime_recovers_scheduling_task_before_destroy`
  creates real scheduling session/task/sandbox rows, simulates a provider
  `NotFound` for the DB-owned runtime, and verifies cleanup moves the task back
  to `pending`, clears sandbox ownership, persists session `rescheduling`, then
  marks the sandbox `destroyed`.
- `cleanup_orphaned_missing_runtime_recovers_running_task_before_destroy`
  creates real running session/task/sandbox rows, simulates a missing provider
  runtime, and verifies cleanup retries the task back to `pending`, increments
  retry count, clears sandbox ownership, persists session `rescheduling`, and
  destroys the stale sandbox row.
- `cleanup_orphaned_missing_runtime_fails_exhausted_running_task_before_destroy`
  creates the same missing-runtime condition at retry exhaustion and verifies
  cleanup fails the task, returns the session to `idle` with the concrete missing
  runtime reason, clears sandbox ownership, and destroys the sandbox row.
- `health_check_dead_bridge_recovers_running_task_before_destroy` creates a real
  DB `running` task whose in-memory bridge has already cleared
  `current_task_id`, simulates a dead provider runtime, and verifies health
  cleanup retries the task to `pending`, persists session `rescheduling`, removes
  the bridge, and only then destroys the sandbox row.
- `health_check_dead_bridge_isolates_row_before_provider_destroy` creates the
  same dead-bridge/running-task condition, records real DB state inside
  `provider.destroy`, and verifies the provider call only runs after the task is
  `pending`, sandbox ownership is cleared, and the sandbox row is isolated as
  `stopping`.
- `non_graceful_reap_recovers_running_task_before_stopping_sandbox` creates a
  real disconnected DB `running` task/sandbox pair, exercises the controller's
  non-graceful stop path, and verifies the task is retried to `pending`, session
  `rescheduling` is persisted, sandbox task ownership is cleared, and only then
  the sandbox is marked `stopped`.
- `non_graceful_reap_isolates_row_before_provider_stop` creates the same real
  disconnected running-task condition, records DB state inside `provider.stop`,
  and verifies the provider call only runs after the task is `pending`, sandbox
  ownership is cleared, and the sandbox row is isolated as `stopping`.
- `provisioning_timeout_does_not_stop_after_running_claim_race` creates a real
  timed-out provisioning sandbox with a scheduling task, records DB state inside
  `provider.stop`, and verifies provisioning cleanup exposes `stopping` rather
  than restartable `stopped` while it repairs the task and stops the runtime.
- `force_stop_stuck_recovers_running_task_before_provider_stop` creates a real
  old `stopping` sandbox that still has a DB-running task, records DB state
  inside `provider.stop`, and verifies force-stop retries the task to `pending`,
  clears sandbox ownership, and only then stops/finalizes the sandbox.
- `sweep_stopped_sandboxes_isolates_row_before_provider_destroy` creates a real
  stopped sandbox aged past the TTL, records DB status at `provider.destroy`,
  and verifies the controller moves the row to `stopping` before any external
  runtime deletion can run, then finalizes it as `destroyed`.
- `destroy_command_rejects_stale_external_id_before_provider_destroy` creates a
  real DB sandbox row, sends a Redis-command-listener destroy payload with a
  stale external id, and verifies the handler fails before `provider.destroy`
  while the current sandbox row remains non-destroyed.
- `destroy_command_claims_row_before_provider_destroy` creates a real DB
  sandbox row, sends a matching destroy payload, records DB status inside
  `provider.destroy`, and verifies the command path isolates the row as
  `stopping` before deleting the external runtime and finalizing `destroyed`.
- `test_delete_agent_rejects_destroy_ack_if_sandbox_external_id_changed`,
  `test_archive_project_rejects_destroy_ack_if_sandbox_external_id_changed`,
  and `test_delete_session_rejects_destroy_ack_if_sandbox_external_id_changed`
  mutate a real sandbox row's external id between Redis destroy publish and ACK
  handling, then verify Python fails closed without deleting/archiving the
  parent resource or marking the replacement sandbox destroyed.
- `sandbox_resolver_stopped_pool_claim_starts_after_db_claim` creates a real
  stopped warm-pool sandbox, records DB status inside `provider.start`, and
  verifies the resolver has already claimed the row as `provisioning` before
  restarting the external runtime.
- `sandbox_resolver_isolates_stale_creating_before_provider_destroy` creates a
  real stale `creating` session sandbox, records DB status at provider destroy,
  and verifies resolver cleanup isolates the row as `stopping` before deleting
  the external runtime and provisioning a replacement sandbox.
- `sandbox_resolver_new_sandbox_error_race_does_not_destroy_changed_runtime`
  creates a real session sandbox through resolver, uses a temporary Postgres
  trigger to make the DB insert land as `error` before `creating ->
  provisioning` CAS, and verifies resolver aborts without calling
  `provider.destroy`.
- `sandbox_resolver_pool_claim_error_race_does_not_destroy_changed_runtime`
  creates a real pooled sandbox, lets provider status polling flip the claimed
  DB row to `error` before metadata attach, and verifies resolver aborts without
  calling `provider.destroy`.
- `sandbox_resolver_pool_ready_error_race_does_not_destroy_changed_runtime`
  creates a real warm-pool provisioning row, uses a temporary Postgres trigger
  to make the DB insert land as `error` before ready finalization, and verifies
  resolver aborts without calling `provider.destroy`.
- `orphaned_task_rescue_marks_session_rescheduling_before_requeue` creates real
  running session/task/sandbox rows, exercises gRPC orphan-task rescue with an
  unreachable Redis queue, and verifies the task/session/event DB state is
  already consistent even when re-enqueue cannot be delivered immediately.
- `orphaned_task_rescue_exhausted_marks_session_idle_without_requeue` creates
  the same real reconnect-rescue condition with the task already at retry limit
  and verifies the task becomes `failed`, the sandbox is released, the session
  moves to `idle`, and no pending retry remains.
- `sandbox_cleanup_exhausted_scheduling_task_marks_session_idle` creates real
  scheduling session/task/sandbox rows at retry limit, exercises gRPC
  `execute_sandbox_cleanup`, and verifies cleanup fails the task and writes one
  task-specific `session.status_idle` event instead of generic
  `sandbox_disconnected` or duplicate `rescheduling`.
- `tests/test_rust_run_spec_real_scenarios.py` invokes the Rust RunSpec snapshot
  scenarios from pytest using the migrated Postgres fixture.
- `test_delete_file_rejects_file_attached_to_active_session_resource` creates a
  real file resource attachment and verifies file deletion returns a structured
  conflict without deleting storage or soft-deleting the file row.
- `harness_input_snapshot_session_file_storage_missing_fails_build` creates real
  project/agent/session/task/file/session-file rows while the referenced object
  is absent from storage, then verifies Rust harness input construction fails
  with the missing storage key instead of starting without the file.
- `build_start_task_full_propagates_harness_input_error_without_minimal_fallback`
  creates the same real missing session-file storage condition at the gRPC
  dispatch boundary and verifies `build_start_task_full` returns the builder
  error instead of producing a minimal `StartTask`.
- `pre_start_failure_marks_task_failed_and_session_idle` creates real
  session/task/sandbox rows and verifies a pre-`StartTask` failure marks the
  task failed, clears the sandbox task association, moves the session back to
  `idle`, and persists exactly one matching `session.status_idle` event.
- `pre_start_failure_does_not_release_sandbox_on_terminal_conflict` creates a
  real running session/task/sandbox row, moves the task terminal first, then
  exercises a stale pre-start failure and verifies task status, sandbox
  ownership, and idle events remain unchanged.
- `pre_start_failure_does_not_fail_pending_task_on_stale_observation` simulates
  a pre-start failure arriving after the task is already back in `pending` and
  verifies it does not mark the task failed, release sandbox ownership again, or
  append a false idle event.
- `start_task_send_failure_retries_and_marks_session_rescheduling` creates real
  running session/task/sandbox rows, sends `StartTask` through a closed outbound
  channel, and verifies the task is returned to `pending` within retry budget,
  the sandbox task association is cleared, the session moves to `rescheduling`,
  and one matching `session.status_rescheduling` event is persisted.
- `dispatch_retry_failure_does_not_release_sandbox_on_terminal_conflict` creates
  a real running session/task/sandbox row, captures a stale running task
  snapshot, moves the task terminal first, and verifies the stale dispatch retry
  path does not change retry count, release the sandbox, or append a false
  rescheduling event.
- `dispatch_retry_failure_does_not_retry_pending_task_on_stale_snapshot` creates
  a real running session/task/sandbox row, captures a stale running task
  snapshot, simulates the task already being back in `pending`, and verifies the
  stale dispatch retry path does not increment retry count, release sandbox
  ownership again, or append a false rescheduling event.
- `start_task_send_failure_exhausts_retries_and_marks_session_idle` creates the
  same real dispatch-send failure at the retry limit and verifies the task
  becomes `failed`, the sandbox is released, the session moves to `idle`, and a
  matching `session.status_idle` event carries the concrete send-failure reason.
- `dispatch_exhausted_failure_does_not_release_sandbox_on_terminal_conflict`
  creates the same stale terminal-conflict condition at retry exhaustion and
  verifies the stale failure path does not overwrite the terminal task, release
  the sandbox, or append a false idle event.
- `dispatch_exhausted_failure_does_not_fail_pending_task_on_stale_snapshot`
  creates the same stale-snapshot condition at retry exhaustion after the task
  is already back in `pending`, and verifies the late failure path does not mark
  the pending task failed or append a false idle event.
- `failover_retry_marks_session_rescheduling_and_releases_sandbox` creates real
  running session/task/sandbox rows, exercises the runtime failover path without
  agent output, and verifies retryable failure returns the task to `pending`,
  clears sandbox ownership, moves the session to `rescheduling`, and persists
  one matching `session.status_rescheduling` event.
- `failover_exhausted_retries_marks_task_failed_and_session_idle` creates the
  same runtime failover condition at the retry limit and verifies the task
  becomes `failed`, sandbox `last_task_id` is cleared, the session moves to
  `idle`, and the persisted idle event carries the concrete failover reason.
- `task_disconnect_before_result_retries_and_marks_session_rescheduling` creates
  real running session/task/sandbox rows, exercises the gRPC pre-result
  disconnect handler, and verifies it returns the task to `pending`, increments
  retry count, releases the sandbox, moves the session to `rescheduling`, and
  persists the matching status event.
- `failover_with_agent_output_completes_task_and_releases_sandbox` creates real
  running session/task/sandbox rows plus a post-running `agent.message`, then
  verifies gRPC failover completes the task, leaves retry count unchanged,
  releases the sandbox, moves the session to `idle(end_turn)`, and persists one
  matching idle event.
- `failover_with_agent_output_does_not_complete_pending_retry` creates the same
  post-running `agent.message` condition, simulates the task already being
  retried to `pending` with session `rescheduling`, then verifies a late gRPC
  failover does not complete the pending retry or append a false
  `idle(end_turn)` event.
- `task_controller_startup_recovery_fails_overdue_running_task_and_idles_session`
  creates real running session/task/sandbox rows with an overdue task and
  verifies startup recovery marks the task failed, releases the sandbox, moves
  the session to `idle`, and persists the matching idle status event.
- `task_controller_overdue_timeout_releases_sandbox_and_idles_session` creates
  real overdue running session/task/sandbox rows, exercises the periodic
  TaskController timeout watchdog, and verifies the task becomes `timeout` with
  completion metadata, the sandbox `last_task_id` is cleared, the session moves
  to `idle(timeout)`, and one matching idle status event is persisted.
- `task_controller_retry_helper_does_not_release_sandbox_on_terminal_conflict`
  creates a real running session/task/sandbox row, moves the task to a terminal
  state first, then exercises a stale retry helper and verifies task status,
  retry count, sandbox ownership, and rescheduling events remain unchanged.
- `task_controller_fail_helper_does_not_release_sandbox_on_terminal_conflict`
  creates the same terminal-conflict condition for the failure helper and
  verifies the stale fail path does not overwrite the terminal task, release the
  sandbox, or append a false idle event.
- `task_controller_runtime_helpers_do_not_mutate_pending_task` creates a real
  task that was already returned to `pending`, then exercises stale runtime retry
  and failure helpers and verifies status, retry count, error, sandbox
  ownership, and session events remain unchanged.
- `task_controller_retry_helper_marks_session_rescheduling` creates real
  session/task/sandbox rows and verifies the scheduling-scoped TaskController
  retry helper returns a scheduling task to `pending`, releases the sandbox,
  moves the session to `rescheduling`, and persists a matching rescheduling
  status event.
- `task_controller_stale_scheduling_retry_does_not_mutate_running_task` creates
  a real running session/task/sandbox row, exercises the scheduling retry helper
  with a stale scheduling observation, and verifies task status/retry count,
  sandbox `running` ownership, session status, and session events remain
  unchanged.
- `task_controller_stale_scheduling_failure_does_not_mutate_running_task`
  creates the same stale-observation condition at retry exhaustion and verifies
  the scheduling failure helper does not mark the running task failed, does not
  release the sandbox, and does not append a false idle status event.
- `task_controller_stuck_scheduling_exhausted_moves_rescheduling_session_idle`
  creates a real `rescheduling` session with a stale scheduling task at retry
  limit and verifies the watchdog failure path can move the session back to
  `idle` with the concrete error reason instead of leaving the user blocked in
  `rescheduling`.
- `task_controller_failover_with_agent_output_completes_and_releases_sandbox`
  creates real running session/task/sandbox rows plus a post-running
  `agent.message`, then verifies TaskController failover completes the task,
  releases the sandbox, and moves the session to `idle(end_turn)`.
- `task_controller_agent_output_failover_does_not_complete_pending_retry`
  creates real running session/task/sandbox rows, persists `agent.message`,
  simulates the task already being retried to `pending` with session
  `rescheduling`, then verifies a late TaskController failover does not complete
  the pending retry or append a false `idle(end_turn)` event.
- `sandbox_resolver_snapshot_session_file_injection_storage_missing_fails_resolve`
  creates real project/agent/session/file/session-file rows with a missing
  storage object and verifies sandbox resolution fails before provider create is
  called.
- `send_setup_waits_for_late_session_link_before_marking_done` creates a real
  unlinked sandbox plus session, links the session shortly after setup begins,
  and verifies `SetupSandbox` is sent only after the late link is visible while
  `bridge.setup_done` remains a caller-owned post-send state.
- `memory_sync_rejects_archived_store_without_mutating_existing_memory` mounts a
  real memory store for a real session, verifies runner memory sync can create a
  memory/version while active, then archives the store and verifies subsequent
  runner update/delete attempts leave content, version, and history unchanged.
- `tests/test_memory_store_lifecycle_active_sessions.py` verifies API/Service
  memory-store archive/delete active-session guards, archived-store readability,
  archived write rejection, cross-project isolation, broadcast routing, path
  validation, preconditions, and live-version redaction conflicts.
- `test_session_service_rejects_direct_memory_attach_for_running_session` and
  `test_session_service_rejects_direct_archived_memory_store_attach` call
  `SessionService.attach_memory_stores` directly against real session/store rows
  and verify no session-memory mount row is created on rejection.
- `test_session_service_rejects_batch_memory_attach_atomically_when_later_store_archived`
  verifies a valid first memory store is not left mounted when a later store in
  the same direct Service batch is archived.
- `test_create_session_duplicate_memory_store_returns_structured_error_without_creating_session`
  verifies duplicate memory resources in `POST /sessions` are rejected before a
  session row is created.
- `test_session_service_rejects_duplicate_memory_attach_before_unique_constraint`
  verifies direct repeated memory-store attach returns a structured conflict and
  preserves the single existing mount instead of surfacing a DB integrity error.
- `test_create_session_duplicate_file_mount_path_returns_structured_error_without_creating_session`
  creates real project/agent/file rows and verifies a duplicate normalized file
  mount path is rejected before a session row is created.
- `test_session_resource_service_rejects_file_mount_path_collision_before_insert`
  directly adds a real file resource, attempts a second file at the same
  normalized workspace path, and verifies only the first mount row exists.
- `test_create_session_duplicate_repo_effective_mount_path_returns_structured_error_without_creating_session`
  verifies two repo resources with omitted `mount_path` but the same
  runner-derived `/workspace/<repo>` destination are rejected before session
  creation.
- `test_session_resource_service_rejects_repo_effective_mount_path_collision_before_insert`
  directly adds a repo with omitted `mount_path`, then rejects another repo whose
  explicit normalized `mount_path` collides with that derived destination.
- `clone_repos_returns_error_for_invalid_mount_path` and
  `clone_repos_returns_error_when_git_clone_fails` verify the sandbox runner
  returns errors for repo setup failures using local deterministic scenarios.
- `handle_setup_fails_when_declared_repo_clone_fails` verifies `SetupSandbox`
  propagates a declared repo clone failure instead of reporting setup complete.
- `handle_setup_fails_when_setup_command_exits_non_zero` runs real shell setup
  commands and verifies a non-zero command fails `SetupSandbox` and prevents a
  later command from mutating the workspace.
- `handle_task_fails_when_fallback_setup_command_exits_before_adapter_run` uses
  the mock adapter registry with a real shell failure and verifies the
  `StartTask` fallback fails before any runner event is emitted or later setup
  command mutates the workspace.
- `handle_setup_fails_when_initial_memory_file_cannot_be_written` uses a real
  filesystem conflict where the declared memory mount path is a file, and
  verifies `SetupSandbox` fails without creating the seed memory file.
- `handle_setup_fails_when_file_ref_download_returns_non_success_status` uses a
  local HTTP server returning 404 and verifies `SetupSandbox` fails without
  creating the declared downloaded file.
- `handle_setup_fails_when_inline_archive_file_cannot_be_extracted` writes a
  recognized `.zip` file with invalid bytes and verifies `SetupSandbox` fails
  instead of silently continuing with an unextracted archive.
- `handle_setup_fails_when_downloaded_archive_cannot_be_extracted` serves an
  invalid `.zip` from a local HTTP server and verifies the downloaded file-ref
  archive failure propagates through `download_file_refs`.
- `setup_failure_result_reports_failed_setup_with_work_dir` verifies the sandbox
  runner sends a structured failed result when `SetupSandbox` fails before any
  task starts.
- `task_failure_result_reports_failed_task_with_context` verifies runner
  preflight failures are reported as failed task results carrying
  `session_id`/`work_dir`, not as idle-only completion.
- `idle_setup_failure_result_marks_sandbox_error_and_clears_setup_done` creates
  a real linked sandbox row, feeds the orchestrator a runner-side setup failure
  result, and verifies `setup_done` is cleared while the sandbox row moves to
  `error` with `config.setup_error`.
- `task_setup_failure_result_marks_task_failed_and_keeps_sandbox_error` creates
  real session/task/sandbox rows, feeds the active task result handler a
  runner-side setup failure, and verifies the task fails, the session goes idle
  with the setup error, and the sandbox remains `error` with `last_task_id`
  cleared.
- `terminal_transition_helper_does_not_rewrite_session_on_cas_conflict` creates
  real running session/task/sandbox rows, cancels the task in DB, persists the
  cancelled session idle event, then exercises a stale timeout transition and
  verifies the task stays `cancelled`, the session stop reason stays
  `cancelled`, and no timeout idle event is appended.
- `late_runner_result_after_cancel_keeps_cancelled_session_authority` creates
  the same real cancellation state, feeds a late successful runner result into
  the active task message handler, and verifies the task output is not updated,
  no fallback `agent.message` is persisted, and the single cancelled idle event
  remains the session authority.
- `test_session_resource_service_rejects_direct_repo_add_for_running_session`
  calls `SessionResourceService.add_repo_resource` directly against a real
  running session and verifies no repo row is created.
- `test_session_resource_service_rejects_direct_repo_mutations_for_running_session`
  calls direct Service repo-token rotation and deletion against a real running
  session and verifies the encrypted token and repo row remain intact.
- `test_session_resource_service_keeps_parent_project_boundary_for_repo_children`
  verifies the Service-level mutable guard does not regress cross-project child
  resource hiding semantics.
- `harness_input_resolves_vlt_prefixed_vault_ids_for_mcp_egress` creates real
  vault/credential/session/task rows and verifies Rust HarnessInputBuilder
  rewrites the MCP URL to the egress placeholder when `vault_ids` uses `vlt_`.
- `sandbox_resolver_builds_mcp_egress_from_vlt_prefixed_vault_ids` creates real
  vault/credential/session/agent rows and verifies SandboxResolver builds Envoy
  MCP egress credentials from the same `vlt_` session reference without exposing
  the token to the sandbox.
- `test_delete_vault_rejects_active_session_reference_without_deleting_row` and
  `test_archive_vault_rejects_vlt_prefixed_active_session_reference` verify
  Vault API delete/archive return structured conflicts and leave the vault row
  unchanged while referenced by resumable sessions.
- `tests/test_rust_vault_real_scenarios.py` invokes the Rust vault alias
  scenarios from pytest using the migrated Postgres fixture.
- `test_cancel_task_rejects_ack_if_task_moved_to_another_sandbox` creates a
  real session/task/sandbox pair, simulates a legal upstream sandbox handoff
  during Redis ACK wait, and verifies the old-runtime cancel ACK cannot mark the
  newly owned task `cancelled` or mark the session idle.
- `test_cancel_task_relays_cancel_to_rust_orchestrator` now covers the normal
  production cancel path with an observed `owner_epoch`, verifying the new
  ownership fence does not reject a still-owned running task.
- `test_scheduler_state_sync_cancel_error_releases_claim_without_advancing`
  verifies schedule `replace` policy treats `TASK_CANCEL_STATE_SYNC_FAILED` as a
  retryable no-advance condition instead of skipping the due slot.

## Next Phases

1. Promote control-event delivery to an explicit command-state table or columns
   if operators need separate queued/sent/runner-acked observability.
2. Decide whether memory-store/repo resource content should remain
   reference-live or gain separate immutable content signatures for long-delay
   scheduled runs.
3. Continue auditing old non-CAS sandbox/task transition helpers. The
   `transition_sandbox()` compatibility wrapper is now guarded, and the current
   hot recovery paths are max-retry aware, but remaining compatibility helpers
   should still not be reused in new production state transitions.
