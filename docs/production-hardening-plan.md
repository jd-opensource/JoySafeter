# JoySafeter 生产韧性 —— 系统性重构详细设计(四地基)

> 状态:详细设计 v3 + 当前实现状态覆盖 · 2026-07-03 · 分支 `joysafeter-v2`
> 前提:**多实例 HA** + **外部/多租户** + 沙箱 **Docker + E2B/Daytona 并存** + 跑道 **>1 个月**。
> 本文代码锚点来自一手深读并在 2026-07-03 文档审计中保留为设计依据；当前实现状态见下方说明。

> **Current status (2026-07-03): partially implemented design, not a runbook.** Current code
> already includes task lease columns, `owner_epoch` fencing, `Idempotency-Key` task creation,
> Redis Stream worker recovery, and event dead-letter handling. The outbox table, durable PG
> cluster membership mirror, provider-chain isolation policy, tenant quota admission, and full
> failure matrix remain design/open implementation items unless verified in a later pass.

---

## 0. 边界(颠覆什么、保留什么、不做什么)

**保留并作为地基实现(勿重写):** 状态机 CAS(`joysafeter_task_state_machine.py`,终态守卫 `WHERE status NOT IN (TERMINAL)`)、领取已用 `FOR UPDATE SKIP LOCKED`(:48/:140)、Redis Streams 消费组 + `xautoclaim`(`stream_consumer.py`)、沙箱多层超时 + 容器加固(`docker_provider.py:134-154`)、启动对账(`task_controller.py:31-157`)、已有实例心跳注册表(`RedisCoordinator`)。

**明确不做(非目标):** Temporal 级持久化工作流 / agent 中途续跑;运行中沙箱跨 provider 热 failover;多地域复制。

**颠覆的是:** 缺失的 fencing、散点式一致性、未接线的多租户、fail-open 姿态。

---

## 地基零 · 可观测前置(先让失败可见)

零行为变更埋点(指标+告警)。落点:`joysafeter_worker/events/batch_writer.py`(队列 drop、10s put 超时)、`stream_publisher.py`(approximate maxlen 裁剪)、`cache/redis.py` 降级、`sandbox_controller.py`(孤儿被杀)、`docker_provider.py`(无上限容器)、`task_controller.py`(任务各状态年龄)。

---

## 地基一 · 集群成员 + 栅栏令牌

**收编:** P0-3、P0-4a、P0-4b、cancel 路由竞态。

### 深读修正(重要)
1. **成员注册表已存在,不新建。** `RedisCoordinator.register_instance/spawn_heartbeat/_list_instance_ids`(`redis_coordinator.py:40-76`),key `joysafeter:instances:{id}` TTL 30s;`settings.instance_id` 默认 hostname(`settings.py:675`),`heartbeat_interval=15/ttl=30`。→ 地基一收窄为"**做成耐久 + 加 fencing epoch**",非造子系统。
2. **`redis.py` 的 no-op 锁是死代码(零调用点)。** 原"删 no-op 锁"打错靶。真正 fail-open 在 `RedisCoordinator.try_acquire_lock`(SET-NX,仅 `sandbox_controller.py:687` pool_manager 用)与**广播式取消路由**(`dispatch_cancel/input` 广播全实例,不定向 owner;`redis_coordinator.py:282-333`)。存在未用的定向 `send_instance_command(target)`(:335-339)。
3. **fencing 是唯一真正缺失的新原语。** 现有 advisory 锁(`task_controller.py:41/170/225/270`、`sandbox_resolver.py:161`、`batch_writer.py:343/421`)全是纯互斥,不发不校验单调令牌。
4. 任务表**无** owner/epoch/lease 列(`joysafeter_task.py`);ownership 今天只在 Redis(`register_sandbox_owner`,`scheduler.py:266`/`grpc/server.py:204-208`,key TTL 300s,值=instance_id)。

### 设计
- **迁移**:`joysafeter_tasks` 加 `owner_instance_id TEXT NULL`、`owner_epoch BIGINT NULL`、`lease_expires_at TIMESTAMPTZ NULL`;索引 `(status, lease_expires_at)`。
- **fencing epoch**:PG sequence `joysafeter_fencing_epoch`;实例在启动/租约续期(改变 ownership 时)`nextval` 取新 epoch。领取任务时把 `owner_instance_id + owner_epoch` 写进 CAS UPDATE(在现有 `claim_pending_batch` 的 UPDATE 里加 SET,`joysafeter_task_state_machine.py:39-58`)。
- **续租**:running 任务每 10s 刷新 `lease_expires_at`;`task_controller` 巡检把 `lease_expires_at < now()` 的 running 判失联 → fail/retry(替代等 `timeout_sec`)。
- **耐久成员**:`RedisCoordinator` 心跳镜像到 PG `cluster_members`(instance_id/role/epoch/heartbeat_at),PG 为孤儿判定权威。
- **容器归属 label**:`docker_provider.py:111-113` 的 label 加 `joysafeter.owner` + `joysafeter.owner_epoch`;`cleanup_orphaned_provider_sandboxes`(`sandbox_controller.py:32-79`)只回收 owner 已死或 epoch 更低者(idle sweep 已按 `get_sandbox_owner` 过滤,:309-314,补齐 provider sweep 这一路)。
- **cmd 路由**:`dispatch_cancel/input` 改用 `get_sandbox_owner` + `send_instance_command(target)` 定向投递。

**验收:** kill orchestrator,其 running 任务数十秒被接管;构造"分区僵尸实例"用旧 epoch 写库/杀容器全部被拒。

---

## 地基二 · 有效一次契约(Outbox + 幂等)

**收编:** P0-1、P0-2、exactly-once。

### 深读修正
1. **状态与事件是两次独立 commit**(`joysafeter_session_service.py:466` 状态、`:577` 事件),丢事件窗口确证存在。AgentBridge 路径更甚(publish 只到 Redis)。
2. **去重是应用级,非 DB 约束**:`joysafeter_session_events` 唯一约束只在 `(session_id, seq)`;PK `id`(uuid7)即 event_id,但去重是 `exists(id)` 检查(`batch_writer.py:373-382`)。→ 需升级为 DB 唯一约束。
3. **提交 INSERT 干净**:`JoySafeterTaskService.create_task`(`joysafeter_task_service.py:31-56`)单行独立事务,无去重——挂幂等约束的理想点。

### 设计
- **幂等**:`joysafeter_tasks` 加 `idempotency_key TEXT`,唯一约束;`create_task` 改 `INSERT ... ON CONFLICT (idempotency_key) DO NOTHING RETURNING`,冲突则查返回既有 task。API 层接收 `Idempotency-Key` 头或按 `(agent_id, session_id, prompt_hash)` 派生。
- **Outbox**:新表 `joysafeter_outbox(id PK, aggregate_id, type, payload JSONB, created_at, published_at NULL, attempts INT, dead BOOL)`。事件产出改为:在 `update_session_status` 的**同一事务内**(commit@:466 之前)插 outbox 行——该 session 已持 `session_id` 行锁 + advisory lock,天然原子。
- **中继**:worker 读 `published_at IS NULL` 行 → `xadd` Redis Stream → 标记 published。内存批缓冲降级为纯吞吐优化(丢了重读 outbox)。
- **去重升级**:outbox id 确定性生成,`session_events` 加 `event_id` 唯一约束,重投真幂等。
- **DLQ**:`attempts` 超阈值 → `dead=true` + 告警。
- **保留**:Redis Streams + xautoclaim 作传输;CAS 状态机作守卫。

**验收:** worker 停 5 分钟再起零丢失;并发双提交一条 task;毒消息进 DLQ 不空转。

---

## 地基三 · 租户与准入(隔离等级)

**收编:** P1-5、P1-6 + 多 provider。

### 深读修正(影响范围)
1. **租户/用户身份根本不到 provisioning。** `resolve()` 只收 `session_id, agent_env, image, networking, engine_kind, project_id`(`sandbox_resolver.py:138-146`);grep 无 `user_id/tenant_id`。→ 配额 enforce 的**前置是把租户身份从 task 一路穿到 resolver/scheduler**,这是跨切面改动,不是"接个旋钮"。
2. **资源限额确实没传**:`create()` 抽象签名 kwargs 化(`provider.py:41-44`),Docker 有 `cpu/memory_mb` kwarg 但 resolver 调用处不传(`sandbox_resolver.py:809-817`)→ Docker 容器无限 CPU/mem。已存在**未用的 `SandboxCreateConfig` 数据类**(`provider.py:16-27`,含 cpu_limit/memory_limit_mb/network)——正好用作资源封套载体。
3. **provider 是进程全局**(`lifespan.py:122-159/239`),无隔离等级概念。但隔离**机制已按 provider 天然不同**:Docker=`NetworkMode=none`+Envoy egress allowlist;E2B=Firecracker VM;cloud provider 拒绝 `"limited"` 网络(`provider.py:85-88`)——这恰好映射成隔离等级抽象。
4. E2B 限额烘焙在 template;Daytona 仅 no-snapshot 分支硬编码(`daytona_provider.py:83-90`)。

### 设计
- **隔离等级枚举**(偏序):`shared_container`(Docker)< `remote_workspace`(Daytona)< `isolated_vm`(E2B)。task/agent 声明**最低**等级。
- **身份穿透**:task 带 `tenant_id`(来源 project/owner),经 scheduler → `resolve()` 落到 sandbox 记录。
- **准入闸门**:领取时按 **DB 计数**该租户在跑沙箱数 enforce `max_concurrent_per_user`(`settings.py:227`,现零引用);全局公平份额。
- **provider chain**:`SandboxProviderChain.select(min_class)` 按等级≥min 的健康 provider 排序;降级只在集合内;空集 → **快速失败不降级**。替换 `lifespan.py` 的单例注入。
- **资源封套**:采用 `SandboxCreateConfig`,把 cpu/mem/pids/disk 经 `_provision_sandbox` 透传 `create()`;给非空默认(`sandbox_cpu/memory_mb`,`settings.py:606/607`)。
- **owner label**:与地基一共用。

**验收:** E2B 宕机时 `isolated_vm` 任务快速失败不降 Docker;单租户并发卡上限;`docker inspect` 见 cgroup 限额;压测单租户吃不满全部槽位。

---

## 地基四 · 故障姿态即不变量(降级矩阵)

**收编:** 真 fail-open(`try_acquire_lock` + 广播路由)、P1-7(S3)、P1-8(订阅者超时)、优雅排空。

| 依赖 | 故障 | 定义行为 | 落点 |
|---|---|---|---|
| Redis | `try_acquire_lock` | 拿不到即失败,不进临界区 | `redis_coordinator.py:155-167` / `sandbox_controller.py:687` |
| Redis | cmd 路由 | 定向失败即显式报错,不静默广播 | `redis_coordinator.py:282-333` |
| Redis | 队列/PubSub | PG 兜底 / 具名降级 DB 轮询 | `queue.py`、`session_broadcast.py` |
| PG | 写 | 边界退避+快速拒绝 | `database.py` |
| S3 | 上传 | 非致命:标记缺失+告警 | `storage/s3.py`(加 `Config(connect_timeout/read_timeout/retries)`) |
| 订阅者 | hang | `wait_for` 超时+指标+继续 | `events/bus.py` |
| 关闭 | in-flight | await `_schedule_task` 排空 + 停/交接容器 | `lifespan`/`scheduler.py` |

**验收:** Game Day 逐格注入验证。

---

## 落地顺序(依赖排序;无大爆炸切换)

1. **地基零(可观测)** — 基线,第 1 周。
2. **地基二(outbox + 幂等)** — 正确性脊柱,相对独立,尽早。
3. **地基四 fail-closed 锁(`try_acquire_lock`)+ 矩阵定稿** — 地基一安全前提。
4. **地基一(耐久成员 + fencing + 归属 label + 定向路由)** — HA 正确性。
5. **地基三(身份穿透 + 准入 + provider chain + 资源封套)** — 依赖地基一做 HA-正确配额计数;身份穿透是其内最大工作量。
6. **地基四全面 enforce + Game Day**。

**Game Day(上线前必做):** kill orchestrator(地基一)、僵尸实例旧 epoch 写入(fencing)、kill Redis(地基四)、worker 停机再起(地基二零丢失)、E2B 宕机(地基三隔离下限)、S3 超时(矩阵)。

---

## 洞 → 地基 映射

| 原洞 | 地基 | 深读结论 |
|---|---|---|
| P0-1 幂等 | 二 | create_task 单点,加唯一约束 |
| P0-2 事件丢失/DLQ | 二 | 两次 commit + 应用级去重 → outbox + DB 约束 |
| P0-3 running 恢复 | 一 | 加 lease,秒级失联检测 |
| P0-4a 锁 fail-closed | 一/四 | 死锁误判修正:目标是 try_acquire_lock + 广播路由 |
| P0-4b 孤儿误杀 | 一 | 加 owner label;idle sweep 已部分过滤 |
| P1-5 provider 容错 | 三 | provider chain + 隔离下限 |
| P1-6 资源/并发 | 三 | 需先做身份穿透,再 enforce |
| P1-7 S3 / P1-8 订阅者 | 四 | 矩阵内 |
