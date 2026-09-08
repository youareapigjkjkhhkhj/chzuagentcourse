# 探索应用：Pod 与 Node 详解

> **对应官方模块**: [Explore your app](https://kubernetes.io/docs/tutorials/kubernetes-basics/explore/explore-intro/)
> **文档定位**: 查看 Pods、Nodes、基本排查

---

## 目录

- [1. Pod 深入理解](#1-pod-深入理解)
- [2. Node 深入理解](#2-node-深入理解)
- [3. Pod 生命周期](#3-pod-生命周期)
- [4. 容器健康检查（Probe）](#4-容器健康检查probe)
- [5. kubectl 排查工具集](#5-kubectl-排查工具集)
- [6. 查看应用配置](#6-查看应用配置)
- [7. 在容器中执行命令](#7-在容器中执行命令)
- [8. Init 容器](#8-init-容器)
- [9. Pod QoS 等级](#9-pod-qos-等级)
- [10. 常见问题排查实战](#10-常见问题排查实战)
- [11. 小结与下一步](#11-小结与下一步)

---

## 1. Pod 深入理解

### 1.1 Pod 是什么

Pod 是 Kubernetes 的**原子调度单位**，代表一个或多个紧密耦合的容器及其共享资源的组合。

```
┌─────────────────────────────────────────┐
│                   Pod                    │
│                                         │
│  ┌──────────────┐  ┌──────────────┐    │
│  │ Container A   │  │ Container B   │    │
│  │ (Web Server)  │  │ (Log Sidecar) │    │
│  │ Port: 8080    │  │               │    │
│  └──────────────┘  └──────────────┘    │
│                                         │
│  共享资源:                                │
│  ┌─────────────────────────────────────┐│
│  │ • 网络: 同一 Pod IP, 共享端口空间     ││
│  │ • 存储: 共享 Volume                  ││
│  │ • 运行信息: 镜像版本、端口、环境变量  ││
│  └─────────────────────────────────────┘│
└─────────────────────────────────────────┘
```

### 1.2 Pod 内容器共享机制

| 共享资源 | 说明 |
|----------|------|
| 网络命名空间 | 同一 Pod 内容器通过 `localhost` 互相访问 |
| IPC 命名空间 | 可通过 IPC（System V IPC、POSIX 消息队列）通信 |
| UTC 命名空间 | 共享主机名 |
| 存储 Volume | 同一 Pod 内容器可挂载相同 Volume |
| IP 地址 | 每个 Pod 一个唯一 IP |

> **注意**: 容器间不共享文件系统（除非显式挂载 Volume）和 PID 命名空间（默认）。

### 1.3 Pod 的 "逻辑主机" 概念

Pod 模拟了一个"逻辑主机"（logical host），适合放置需要紧密协作的容器：

**典型多容器 Pod 示例**:

```
┌───────────────────────────────────────┐
│              Web App Pod               │
│                                       │
│  ┌──────────────┐  ┌──────────────┐  │
│  │ Node.js App  │  │ File Updater │  │
│  │ (读文件对外   │  │ (从远程拉取   │  │
│  │  提供服务)    │  │  文件到共享   │  │
│  │              │  │  Volume)     │  │
│  └──────┬───────┘  └──────┬───────┘  │
│         │                  │          │
│         └──── 共享 Volume ──┘          │
│              /var/www/data             │
└───────────────────────────────────────┘
```

### 1.4 Pod 常见设计模式

| 模式 | 说明 | 示例 |
|------|------|------|
| Sidecar（边车） | 辅助主容器 | 日志收集、配置同步 |
| Ambassador（代理） | 代理外部服务连接 | 数据库代理 |
| Adapter（适配器） | 标准化接口 | 监控指标转换 |
| Init Container | 初始化任务 | 等待依赖服务就绪 |

---

## 2. Node 深入理解

### 2.1 Node 是什么

Node 是 Kubernetes 集群中的**工作机器**，可以是虚拟机或物理机。每个 Node 由控制平面管理，可以运行多个 Pod。

```
┌─────────────────────────────────────────────┐
│                   Node                        │
│                                               │
│  ┌──────────────────────────────────────┐    │
│  │ kubelet (节点代理)                     │    │
│  │ • 与控制平面通信                       │    │
│  │ • 管理 Pod 生命周期                    │    │
│  │ • 执行健康检查                         │    │
│  └──────────────────────────────────────┘    │
│                                               │
│  ┌──────────────────────────────────────┐    │
│  │ kube-proxy (网络代理)                  │    │
│  │ • 维护 Service 网络规则                │    │
│  │ • 负载均衡到后端 Pod                   │    │
│  └──────────────────────────────────────┘    │
│                                               │
│  ┌──────────────────────────────────────┐    │
│  │ Container Runtime (容器运行时)         │    │
│  │ • containerd / CRI-O                  │    │
│  │ • 拉取镜像、运行容器                   │    │
│  └──────────────────────────────────────┘    │
│                                               │
│  ┌────────┐  ┌────────┐  ┌────────┐         │
│  │ Pod 1  │  │ Pod 2  │  │ Pod 3  │         │
│  │(Nginx) │  │(Redis) │  │(App)   │         │
│  └────────┘  └────────┘  └────────┘         │
└─────────────────────────────────────────────┘
```

### 2.2 Node 状态

```bash
kubectl describe node minikube
```

**Node Conditions（状态条件）**:

| Condition | 说明 | 健康值 |
|-----------|------|--------|
| Ready | 节点是否健康 | True |
| DiskPressure | 磁盘空间不足 | False |
| MemoryPressure | 内存不足 | False |
| PIDPressure | 进程数过多 | False |
| NetworkUnavailable | 网络配置错误 | False |

### 2.3 Node 资源管理

```bash
# 查看节点资源使用情况
kubectl describe node minikube

# 关键信息:
# Capacity:     节点总资源
# Allocatable:  可分配给 Pod 的资源
# Allocated resources: 已分配资源
```

```
Capacity:
  cpu:                4
  memory:             8174844Ki
  pods:               110
Allocatable:
  cpu:                3500m
  memory:             8072444Ki
  pods:               110
Allocated resources:
  (Total limits may be over 100 percent, i.e., overcommitted.)
  Resource           Requests     Limits
  --------           --------     ------
  cpu                350m (10%)   700m (20%)
  memory             256Mi (3%)   512Mi (6%)
```

### 2.4 Node 调度控制

**污点与容忍（Taints and Tolerations）**:

```bash
# 给节点添加污点（阻止 Pod 调度）
kubectl taint nodes node1 key=value:NoSchedule

# 移除污点
kubectl taint nodes node1 key:NoSchedule-
```

**节点选择器（nodeSelector）**:

```yaml
spec:
  nodeSelector:
    disktype: ssd
```

**节点亲和性（nodeAffinity）**:

```yaml
spec:
  affinity:
    nodeAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        nodeSelectorTerms:
        - matchExpressions:
          - key: kubernetes.io/arch
            operator: In
            values:
            - amd64
```

---

## 3. Pod 生命周期

### 3.1 Pod 生命周期阶段

```
            创建 Pod
               ↓
          ┌─────────┐
          │ Pending  │  ← 等待调度/拉取镜像
          └────┬─────┘
               ↓
          ┌─────────┐
          │ Running  │  ← 容器运行中
          └────┬─────┘
               ↓
     ┌─────────┴──────────┐
     ↓                    ↓
┌─────────┐         ┌─────────┐
│Succeeded│         │ Failed  │
│ (正常完成)│         │ (异常终止)│
└─────────┘         └─────────┘
```

| 阶段 | 说明 |
|------|------|
| Pending | Pod 已创建，等待调度或镜像拉取 |
| Running | Pod 已绑定到节点，至少一个容器运行中 |
| Succeeded | 所有容器成功终止（不会重启） |
| Failed | 所有容器终止，至少一个失败 |
| Unknown | 无法确定状态（通常是与节点通信失败） |

### 3.2 容器状态

| 状态 | 说明 |
|------|------|
| Waiting | 容器正在创建（拉取镜像、准备环境） |
| Running | 容器正常运行 |
| Terminated | 容器已终止（成功或失败） |

```bash
# 查看容器状态
kubectl describe pod <pod-name>
# 关注 Containers → State 字段
```

### 3.3 Pod 重启策略

```yaml
spec:
  restartPolicy: Always    # 总是重启（默认，Deployment 必须用 Always）
  # OnFailure: 只在失败时重启
  # Never: 从不重启
```

### 3.4 Pod 终止流程

```
1. 删除 Pod 请求
       ↓
2. Pod 进入 Terminating 状态
       ↓
3. 执行 preStop 钩子（如果有）
       ↓
4. 发送 SIGTERM 信号给容器
       ↓
5. 等待 terminationGracePeriodSeconds（默认 30s）
       ↓
6. 如果超时，发送 SIGKILL 强制终止
       ↓
7. 清理资源
```

**优雅终止配置**:

```yaml
spec:
  terminationGracePeriodSeconds: 60
  containers:
  - name: app
    image: myapp:v1
    lifecycle:
      preStop:
        exec:
          command:
          - "/bin/sh"
          - "-c"
          - "nginx -s quit; while killall -0 nginx; do sleep 1; done"
```

---

## 4. 容器健康检查（Probe）

### 4.1 三种探针类型

| 探针类型 | 功能 | 失败后果 |
|----------|------|----------|
| livenessProbe（存活探针） | 检查容器是否"活着" | 重启容器 |
| readinessProbe（就绪探针） | 检查容器是否"就绪" | 从 Service Endpoints 移除（不转发流量） |
| startupProbe（启动探针） | 检查容器是否"已启动" | 禁用 liveness/readiness 直到启动成功 |

```
容器启动
    ↓
startupProbe 检查 (可选)
    ↓ 启动成功
livenessProbe 开始    readinessProbe 开始
    ↓                      ↓
存活? → 不存活 → 重启    就绪? → 不就绪 → 移出 Service
```

### 4.2 三种探测方式

| 方式 | 说明 | 示例 |
|------|------|------|
| HTTP GET | 向容器发送 HTTP 请求，2xx/3xx 为成功 | `httpGet: path: /health port: 8080` |
| TCP Socket | 尝试 TCP 连接指定端口 | `tcpSocket: port: 3306` |
| Exec | 在容器内执行命令，退出码 0 为成功 | `exec: command: ["cat", "/tmp/healthy"]` |

### 4.3 完整探针配置示例

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: web-app
spec:
  containers:
  - name: nginx
    image: nginx:1.25
    ports:
    - containerPort: 80

    # 启动探针（慢启动应用专用）
    startupProbe:
      httpGet:
        path: /healthz
        port: 80
      initialDelaySeconds: 0
      periodSeconds: 5
      failureThreshold: 30    # 30×5=150s 启动超时

    # 存活探针（检测死锁等不可恢复状态）
    livenessProbe:
      httpGet:
        path: /healthz
        port: 80
      initialDelaySeconds: 10
      periodSeconds: 10
      timeoutSeconds: 2
      failureThreshold: 3

    # 就绪探针（检测是否可以接收流量）
    readinessProbe:
      httpGet:
        path: /ready
        port: 80
      initialDelaySeconds: 5
      periodSeconds: 5
      timeoutSeconds: 2
      failureThreshold: 3

    # 生命周期钩子
    lifecycle:
      postStart:              # 容器启动后执行
        exec:
          command: ["/bin/sh", "-c", "echo 'Started' > /tmp/start.log"]
      preStop:                # 容器终止前执行
        exec:
          command: ["/bin/sh", "-c", "nginx -s quit"]
```

### 4.4 探针配置参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| initialDelaySeconds | 0 | 容器启动后首次探测的延迟 |
| periodSeconds | 10 | 探测间隔 |
| timeoutSeconds | 1 | 探测超时时间 |
| successThreshold | 1 | 连续成功次数（就绪探针可用 1-3） |
| failureThreshold | 3 | 连续失败次数后判定为失败 |

### 4.5 探针最佳实践

1. **livenessProbe 和 readinessProbe 使用不同端点**
   - liveness: `/healthz`（检测进程是否存活）
   - readiness: `/ready`（检测依赖是否就绪）

2. **慢启动应用使用 startupProbe**
   - Java 应用启动可能需要 1-2 分钟
   - 不配置 startupProbe 会被 livenessProbe 误杀

3. **livenessProbe 失败阈值适当放宽**
   - 避免高负载时误杀导致级联故障

4. **readinessProbe 严格检查**
   - 确保数据库连接、缓存等依赖就绪

---

## 5. kubectl 排查工具集

### 5.1 四大核心排查命令

```bash
kubectl get        # 列出资源
kubectl describe   # 显示资源详细信息
kubectl logs       # 打印容器日志
kubectl exec       # 在容器中执行命令
```

### 5.2 get - 列出资源

```bash
# 查看各类资源
kubectl get pods
kubectl get pods -o wide              # 宽输出
kubectl get pods -n kube-system       # 指定命名空间
kubectl get pods --all-namespaces     # 所有命名空间
kubectl get pods -l app=nginx         # 按标签筛选
kubectl get pods --show-labels        # 显示标签
kubectl get pods --sort-by=.status.startTime  # 按时间排序
kubectl get pods --field-selector status.phase=Running  # 按状态筛选
```

### 5.3 describe - 显示详细信息

```bash
# 查看 Pod 详情（最常用排查命令）
kubectl describe pod <pod-name>

# 查看 Node 详情
kubectl describe node <node-name>

# 查看 Deployment 详情
kubectl describe deployment <name>

# 查看 Service 详情
kubectl describe service <name>
```

> `describe` 输出是人类可读的，设计用于排查而非脚本化。

### 5.4 logs - 查看容器日志

```bash
# 查看当前日志
kubectl logs <pod-name>

# 查看上一个容器的日志（容器崩溃后）
kubectl logs <pod-name> --previous

# 实时跟踪日志
kubectl logs -f <pod-name>

# 查看最近 N 行
kubectl logs <pod-name> --tail=100

# 查看指定时间后的日志
kubectl logs <pod-name> --since=1h

# 多容器 Pod 指定容器
kubectl logs <pod-name> -c <container-name>
```

### 5.5 exec - 在容器中执行命令

```bash
# 执行单条命令
kubectl exec <pod-name> -- env

# 交互式终端
kubectl exec -it <pod-name> -- bash

# 指定容器
kubectl exec -it <pod-name> -c <container-name> -- bash

# 执行命令并获取输出
kubectl exec <pod-name> -- ls /app
```

---

## 6. 查看应用配置

### 6.1 查看 Pod 列表

```bash
kubectl get pods
```

### 6.2 查看 Pod 详情

```bash
kubectl describe pods
```

**关键字段解读**:

```
Name:         kubernetes-bootcamp-77b4f7f7d4-9p2xk
Namespace:    default                     # 命名空间
Node:         minikube/192.168.49.2       # 运行节点
Status:       Running                     # 运行状态
IP:           172.17.0.4                  # Pod IP
Containers:
  kubernetes-bootcamp:
    Image:          gcr.io/...:v1        # 镜像
    State:          Running               # 容器状态
    Ready:          True                  # 是否就绪
    Restart Count:  0                     # 重启次数
    Environment:                          # 环境变量
    Mounts:                               # 卷挂载
Events:                                   # 事件历史（排查关键）
  Normal  Scheduled  2m  default-scheduler  Successfully assigned...
  Normal  Pulling    2m  kubelet            Pulling image...
  Normal  Pulled     1m  kubelet            Successfully pulled image
  Normal  Created    1m  kubelet            Created container
  Normal  Started    1m  kubelet            Started container
```

### 6.3 通过代理访问应用

```bash
# 启动代理（第二终端）
kubectl proxy

# 获取 Pod 名称
export POD_NAME="$(kubectl get pods -o go-template --template '{{range .items}}{{.metadata.name}}{{"\n"}}{{end}}')"
echo "Pod Name: $POD_NAME"

# 通过 API 代理访问
curl http://localhost:8001/api/v1/namespaces/default/pods/$POD_NAME:8080/proxy/
```

---

## 7. 在容器中执行命令

### 7.1 查看环境变量

```bash
kubectl exec "$POD_NAME" -- env
```

输出：
```
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
HOSTNAME=kubernetes-bootcamp-77b4f7f7d4-9p2xk
KUBERNETES_SERVICE_PORT=443
KUBERNETES_SERVICE_HOST=10.96.0.1
...
```

### 7.2 进入容器终端

```bash
kubectl exec -ti $POD_NAME -- bash
```

进入容器后可以：
```bash
# 查看应用源码
cat server.js

# 在容器内部测试应用
curl http://localhost:8080

# 查看进程
ps aux

# 退出
exit
```

> 在容器内使用 `localhost:8080` 是因为你在 Pod 内部，直接访问容器端口。

---

## 8. Init 容器

### 8.1 Init 容器概念

Init 容器在主容器启动前运行，用于完成初始化操作：

```
Pod 启动
  ↓
Init Container 1 (等待数据库就绪)
  ↓ 成功完成
Init Container 2 (初始化配置文件)
  ↓ 成功完成
Main Container (应用启动)
```

**特点**:
- 必须按顺序执行，前一个成功后才启动下一个
- 全部成功后才启动主容器
- 失败则按重启策略重启整个 Pod
- 不支持 readiness/liveness 探针

### 8.2 Init 容器示例

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: myapp
spec:
  initContainers:
  # Init 容器 1: 等待 MySQL 就绪
  - name: wait-for-db
    image: busybox:1.34
    command: ['sh', '-c', 'until nslookup mysql; do echo waiting for mysql; sleep 2; done']

  # Init 容器 2: 初始化数据
  - name: init-data
    image: busybox:1.34
    command: ['sh', '-c', 'echo "Initializing..." > /data/init.txt']
    volumeMounts:
    - name: data
      mountPath: /data

  containers:
  - name: myapp
    image: myapp:v1
    volumeMounts:
    - name: data
      mountPath: /app/data

  volumes:
  - name: data
    emptyDir: {}
```

### 8.3 Sidecar 容器（K8S 1.33+ 稳定）

```yaml
spec:
  initContainers:
  # Sidecar 容器（restartPolicy: Always）
  - name: log-shipper
    image: log-shipper:v1
    restartPolicy: Always    # 标记为 sidecar
    volumeMounts:
    - name: logs
      mountPath: /var/log/app

  containers:
  - name: app
    image: myapp:v1
    volumeMounts:
    - name: logs
      mountPath: /var/log/app
```

> Sidecar 容器在主容器之前启动，在 Pod 整个生命周期中运行。

---

## 9. Pod QoS 等级

Kubernetes 根据 resource requests 和 limits 自动为 Pod 分配 QoS（服务质量）等级：

| QoS 等级 | 条件 | 驱逐优先级 |
|----------|------|------------|
| Guaranteed | 所有容器都设置了 requests 和 limits，且 requests=limits | 最低（最后被驱逐） |
| Burstable | 至少一个容器设置了 requests，但不是 Guaranteed | 中等 |
| BestEffort | 所有容器都没有设置 requests 和 limits | 最高（最先被驱逐） |

```yaml
# Guaranteed (requests == limits)
resources:
  requests:
    cpu: "200m"
    memory: "256Mi"
  limits:
    cpu: "200m"
    memory: "256Mi"

# Burstable (requests < limits 或部分设置)
resources:
  requests:
    cpu: "100m"
    memory: "128Mi"
  limits:
    cpu: "200m"
    memory: "256Mi"

# BestEffort (无 requests/limits)
# 不设置 resources 字段
```

**节点资源不足时的驱逐顺序**: BestEffort → Burstable（超限的）→ Guaranteed

---

## 10. 常见问题排查实战

### 10.1 Pod 处于 Pending 状态

```bash
kubectl describe pod <pod-name>
# 查看 Events 部分
```

**常见原因**:
- 资源不足：节点 CPU/内存不够
- 调度约束：nodeSelector/Affinity/Taint 不匹配
- PVC 未就绪：等待存储卷

### 10.2 Pod 处于 ImagePullBackOff / ErrImagePull

```bash
kubectl describe pod <pod-name>
```

**原因**: 镜像拉取失败

**排查**:
```bash
# 1. 检查镜像名称和标签
# 2. 检查镜像仓库是否可达
# 3. 检查 imagePullSecrets
kubectl get secret <secret-name> -o yaml
```

### 10.3 Pod 处于 CrashLoopBackOff

```bash
# 查看容器日志
kubectl logs <pod-name>
kubectl logs <pod-name> --previous

# 进入容器排查（如果容器能短暂运行）
kubectl exec -it <pod-name> -- bash
```

**常见原因**:
- 应用启动错误（配置错误、依赖缺失）
- 存活探针配置不当（误判为不健康）
- 权限问题

### 10.4 Pod 处于 Terminating 卡住

```bash
# 检查是否有 finalizer
kubectl get pod <pod-name> -o yaml | grep finalizers

# 强制删除（谨慎使用）
kubectl delete pod <pod-name> --grace-period=0 --force
```

### 10.5 Pod 健康检查失败

```bash
# 查看探针失败事件
kubectl describe pod <pod-name>
# 查看 Events 中的 Warning 信息

# 手动测试探针端点
kubectl exec -it <pod-name> -- curl http://localhost:8080/healthz
```

### 10.6 排查清单

```
□ kubectl get pods -o wide          # 查看 Pod 状态和所在节点
□ kubectl describe pod <pod-name>   # 查看 Events，定位问题
□ kubectl logs <pod-name>           # 查看应用日志
□ kubectl logs <pod-name> --previous # 查看崩溃前日志
□ kubectl exec -it <pod-name> -- bash # 进入容器排查
□ kubectl get events --sort-by='.metadata.creationTimestamp' # 查看集群事件
```

---

## 11. 小结与下一步

### 核心知识点回顾

1. **Pod** 是 K8S 原子调度单位，内部容器共享网络和存储
2. **Node** 是工作机器，运行 kubelet、kube-proxy 和容器运行时
3. **Pod 生命周期**: Pending → Running → Succeeded/Failed
4. **三种探针**: startup（启动）、liveness（存活）、readiness（就绪）
5. **kubectl 四大排查命令**: get、describe、logs、exec
6. **Init 容器** 用于初始化，Sidecar 容器用于辅助主容器
7. **QoS 等级**: Guaranteed > Burstable > BestEffort

### 下一步

- [通过 Service 对外暴露应用](K8S技术文档-04-通过Service对外暴露应用.md)
- [Kubernetes 官方 Pod 文档](https://kubernetes.io/docs/concepts/workloads/pods/)
- [Kubernetes 官方 Node 文档](https://kubernetes.io/docs/concepts/architecture/nodes/)
- [Kubernetes 探针配置指南](https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/)

---

> **参考资料**:
> - [Kubernetes 官方教程 - Explore Your App](https://kubernetes.io/docs/tutorials/kubernetes-basics/explore/explore-intro/)
> - [Kubernetes 官方 Pod 概念](https://kubernetes.io/docs/concepts/workloads/pods/)
> - [Kubernetes 官方 Pod 生命周期](https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/)
> - [Kubernetes 探针配置](https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/)
> - [Mastering Kubernetes Pod Lifecycle](https://www.besthub.dev/articles/mastering-kubernetes-pod-lifecycle-and-restart-policies-a-hands-on-guide-2e106ec3a9de)
