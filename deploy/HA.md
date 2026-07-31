# High-Availability: distributed trigger scheduler

The cron **scheduler** and webhook/task **execution** are designed to run as
multiple concurrent instances with no leader election. This doc covers how to
run the control plane (scheduler) as multiple replicas and how to drill it.

## Why it's safe to run N workers

The scheduler lives in the `worker` service. Multi-instance correctness rests on
mechanisms already in the code (not new to this deploy):

- **Competing-consumer claim** — `JoySafeterTriggerService.claim_due_cron_triggers`
  selects due cron triggers `FOR UPDATE SKIP LOCKED` and stamps `locked_by` /
  `locked_at`. Two workers claiming at the same instant get **disjoint** trigger
  sets, so a slot is never processed twice.
- **Stale-lock reclaim** — a worker that crashes mid-fire leaves a lock behind;
  after `SCHEDULER_LOCK_GRACE_SEC` (default 120s) a survivor reclaims it, so **no
  slot is lost**.
- **Exactly-once effect** — every fire carries an idempotency key
  `trigger:cron:{id}:{slot_epoch}` (attempt-suffixed on retry) unique-constrained
  on `joysafeter_tasks.idempotency_key`; a duplicate fire collapses to one task.
- **Unique instance identity** — the scheduler `worker_id` and the Redis
  event-stream consumer name both derive from `hostname + uuid`, and the
  event-stream worker uses a Redis **consumer group** (`xreadgroup`), so N
  workers share the stream as competing consumers with no double-persist.

These are exercised by `backend/tests/test_scheduler_ha_concurrent_claim.py`
(SKIP LOCKED disjointness + stale-lock reclaim) and the P0/P1/P2 trigger tests
(idempotency, retry/backoff, dead-letter).

## Run multiple workers

```bash
cd deploy
# either:
docker compose --profile local-redis --profile rust-orchestrator up -d --scale worker=3
# or with the overlay (WORKER_REPLICAS defaults to 3):
docker compose -f docker-compose.yml -f docker-compose.ha.yml \
  --profile local-redis --profile rust-orchestrator up -d
```

The `worker` service has no `container_name` and does not publish a fixed host
port, so it scales cleanly. Keep `WORKERS=1` per container (one scheduler loop
per process) and scale by adding **container replicas**, not uvicorn workers.

## Chaos drill — no lost slot, no duplicate

1. Scale to 3 workers (above). Create several **every-minute** cron triggers in
   the UI (`/managed/triggers`).
2. Watch fires land as tasks: `docker compose logs -f worker | grep "Scheduler claimed"`.
3. Mid-minute, kill one worker: `docker kill $(docker ps -q -f name=worker | head -1)`.
4. Assert the invariant per trigger: exactly one task per due slot, none missing.
   For a trigger `trig_<id>`, in Postgres:
   ```sql
   SELECT idempotency_key, count(*)
   FROM joysafeter_tasks
   WHERE trigger_id = '<uuid>'
   GROUP BY idempotency_key HAVING count(*) > 1;   -- must return 0 rows (no duplicate)
   ```
   The killed worker's in-flight slot is reclaimed by a survivor within
   `SCHEDULER_LOCK_GRACE_SEC` (no lost slot); slot idempotency guarantees no
   duplicate even if the crash happened between claim and fire.

## Scaling the orchestrator (task data plane) — next step, not yet wired

`orchestrator-rs` is **correctness-safe** under multiple instances already:
`owner_epoch` fencing tokens, `lease_expires_at` + watchdog reclaim, and
`FOR UPDATE SKIP LOCKED` task claiming (`JOYSAFETER_INSTANCE_ID` falls back to
the container hostname when unset, so replicas get distinct identities). It is
kept single-replica in compose because each replica must publish a **distinct,
sandbox-reachable gRPC address** (`JOYSAFETER_GRPC_PUBLIC_URL`) for its sandbox
runners to connect back to — a networking concern (per-replica published port or
a gRPC-aware load balancer) that this compose setup does not yet solve. Wiring
that (e.g. one published port per replica, or routing through Envoy) is the
remaining infra step for full data-plane HA.
