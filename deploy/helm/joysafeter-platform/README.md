# JoySafeter Platform Helm Chart

该 Chart 统一管理 JoySafeter 跨 namespace 共享的集群级资源。目前包括：

- `joysafeter-production` PriorityClass
- `AgentIdentityService` CRD

平台资源只安装一次，不要分别安装到 dev、pre、prod release。建议将 Helm release
metadata 放在独立的 `joysafeter-system` namespace：

```bash
helm upgrade --install joysafeter-platform . \
  --namespace joysafeter-system \
  --create-namespace
```

Helm 不会在已有 release 的 `upgrade` 中安装或升级 `crds/` 下的定义。若
`joysafeter-platform` 已经存在，首次引入或后续升级该 CRD 时先执行：

```bash
kubectl apply -f crds/agentidentityservices.security.joysafeter.io.yaml
helm upgrade joysafeter-platform . --namespace joysafeter-system
```

应用 Chart 必须在平台 Chart 安装完成后部署。卸载平台 Chart 前，应先确认没有工作负载
继续引用其集群级资源。

CRD 定义由三个环境共享，具体 `AgentIdentityService` 资源由应用 Chart 创建在各自
namespace 中，所以 dev、pre、prod 的信任目标互不影响。`spec.host` 支持精确域名和
`*.example.com`；通配符只匹配子域，不匹配根域。裸 `*`、中间通配符和 IP 通配符会被
拒绝。Orchestrator 通过 List/Watch 热更新内存快照，不需要重启。
