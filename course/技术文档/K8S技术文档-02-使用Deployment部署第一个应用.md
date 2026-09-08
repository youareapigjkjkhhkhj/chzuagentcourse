# 使用 Deployment 部署第一个应用

> **对应官方模块**: [Deploy an app](https://kubernetes.io/docs/tutorials/kubernetes-basics/deploy-app/deploy-intro/)
> **文档定位**: 部署容器化应用、Deployment 核心概念

---

## 目录

- [1. Deployment 核心概念](#1-deployment-核心概念)
- [2. Pod 详解](#2-pod-详解)
- [3. ReplicaSet 与 Deployment 的关系](#3-replicaset-with-deployment)
- [4. kubectl 基础操作](#4-kubectl-基础操作)
- [5. 部署第一个应用](#5-部署第一个应用)
- [6. 查看部署状态](#6-查看部署状态)
- [7. 通过代理访问应用](#7-通过代理访问应用)
- [8. YAML 方式创建 Deployment](#8-yaml-方式创建-deployment)
- [9. 镜像管理最佳实践](#9-镜像管理最佳实践)
- [10. Deployment 生命周期管理](#10-deployment-生命周期管理)
- [11. 常见问题排查](#11-常见问题排查)
- [12. 小结与下一步](#12-小结与下一步)

---

## 1. Deployment 核心概念

### 1.1 什么是 Deployment

Deployment 是 Kubernetes 中最常用的工作负载控制器，负责**创建和更新应用实例**。

**核心职责**:
- 定义应用的期望状态（镜像、副本数、配置等）
- 创建并管理 Pod 实例
- 提供自愈能力（节点故障时自动迁移 Pod）
- 支持滚动更新和回滚

```
Deployment (期望状态: 3 副本)
       ↓ 创建
   ReplicaSet (管理副本)
       ↓ 创建
     Pod × 3 (运行容器)
```

### 1.2 为什么需要 Deployment

在传统部署模式中，安装脚本启动应用后**无法自动恢复机器故障**：

```
传统模式:                           K8S Deployment 模式:
┌──────────┐                       ┌──────────────────┐
│ 脚本启动   │  机器故障 → 应用停止    │ Deployment       │
│ 应用      │  无法自愈              │  ↓ 监控           │
└──────────┘                       │ Pod 故障 → 自动重建│
                                   │ 节点故障 → 自动迁移│
                                   └──────────────────┘
```

Deployment Controller 持续监控应用实例，如果节点宕机或 Pod 被删除，控制器会自动在其他节点上创建新实例，实现**自愈**。

### 1.3 Deployment 的自愈机制

```
                ┌─────────────────────────┐
                │  Deployment Controller  │
                │  期望副本数: 3            │
                └──────────┬──────────────┘
                           │ 持续监控
              ┌────────────┼────────────┐
              ▼            ▼            ▼
         ┌─────────┐ ┌─────────┐ ┌─────────┐
         │  Pod 1  │ │  Pod 2  │ │  Pod 3  │
         │  Node A │ │  Node B │ │  Node A │
         └─────────┘ └─────────┘ └─────────┘
                           ↓ Node B 故障
              ┌────────────┼────────────┐
              ▼            ▼            ▼
         ┌─────────┐ ┌─────────┐ ┌─────────┐
         │  Pod 1  │ │  Pod 4  │ │  Pod 3  │
         │  Node A │ │  Node C │ │  Node A │
         └─────────┘ └─────────┘ └─────────┘
                     ↑ 自动在 Node C 重建
```

---

## 2. Pod 详解

### 2.1 什么是 Pod

Pod 是 Kubernetes 中**最小的可部署单元**，是一个或多个容器的组合，包含共享资源：

```
┌───────────────────────────────────┐
│              Pod                   │
│  ┌────────────┬────────────────┐  │
│  │ Container A│  Container B    │  │
│  │ (Web Server)│ (Log Sidecar)  │  │
│  └────────────┴────────────────┘  │
│  ┌───────────────────────────────┐│
│  │ 共享资源:                       ││
│  │ • 网络: 同一 IP + 端口空间      ││
│  │ • 存储: 共享 Volume             ││
│  │ • 运行配置: 镜像版本、端口等    ││
│  └───────────────────────────────┘│
└───────────────────────────────────┘
```

**Pod 特性**:
- 每个 Pod 拥有唯一的 IP 地址
- Pod 内容器共享网络命名空间（可通过 localhost 互相访问）
- Pod 内容器共享存储卷（Volume）
- Pod 总是调度到同一个节点上运行
- Pod 是临时的（ephemeral），可以被创建和销毁

### 2.2 Pod 的两种使用模式

**模式一：单容器 Pod（最常见）**
```
Pod = 一个容器（如 Nginx Web Server）
```

**模式二：多容器 Pod（紧耦合场景）**
```
Pod = Web Server + File Refresh Sidecar
     （Web Server 提供文件访问，Sidecar 定期更新文件）
```

> 只有需要紧密协作、共享资源的容器才放在同一个 Pod 中。

### 2.3 Pod 与 Deployment 的关系

```
Deployment
  └── ReplicaSet (v1)
        ├── Pod-1 (container: app:v1)
        ├── Pod-2 (container: app:v1)
        └── Pod-3 (container: app:v1)
```

**重要概念**:
- 创建 Deployment 时，Deployment 自动创建 ReplicaSet
- ReplicaSet 负责维持指定数量的 Pod 副本
- 你通常不直接操作 Pod，而是通过 Deployment 管理

---

## 3. ReplicaSet 与 Deployment 的关系

### 3.1 层级关系

```
用户创建 Deployment → Deployment 创建 ReplicaSet → ReplicaSet 创建 Pod
```

| 资源 | 职责 |
|------|------|
| Deployment | 管理应用版本、滚动更新、回滚 |
| ReplicaSet | 维持指定数量的 Pod 副本 |
| Pod | 运行容器实例 |

### 3.2 滚动更新时的层级变化

```
更新镜像版本 v1 → v2:

Deployment
  ├── ReplicaSet-v1 (副本数: 2 → 0，逐步减少)
  │     ├── Pod-1 (v1) → 终止
  │     └── Pod-2 (v1) → 终止
  └── ReplicaSet-v2 (副本数: 0 → 2，逐步增加)
        ├── Pod-3 (v2) → 新建
        └── Pod-4 (v2) → 新建
```

> Deployment 通过管理多个 ReplicaSet 版本实现滚动更新和回滚。

---

## 4. kubectl 基础操作

### 4.1 命令格式

kubectl 命令的基本格式：`kubectl action resource`

```bash
# action: create, get, describe, delete, apply, scale...
# resource: pod, deployment, service, node...
```

### 4.2 常用命令速查

```bash
# 集群信息
kubectl version              # 查看客户端和服务端版本
kubectl cluster-info         # 查看集群信息
kubectl get nodes            # 查看节点列表

# 资源操作
kubectl get deployments      # 查看 Deployment 列表
kubectl get pods             # 查看 Pod 列表
kubectl get rs               # 查看 ReplicaSet 列表
kubectl get all              # 查看所有资源

# 详情查看
kubectl describe deployment <name>  # 查看 Deployment 详情
kubectl describe pod <name>         # 查看 Pod 详情

# 日志与执行
kubectl logs <pod-name>             # 查看 Pod 日志
kubectl exec -it <pod-name> -- bash # 进入容器

# 帮助
kubectl get nodes --help    # 获取子命令帮助
```

### 4.3 输出格式

```bash
# 宽输出（显示 IP、Node 等）
kubectl get pods -o wide

# YAML 格式
kubectl get deployment <name> -o yaml

# JSON 格式
kubectl get deployment <name> -o json

# 自定义列
kubectl get pods -o custom-columns=NAME:.metadata.name,STATUS:.status.phase

# Go Template（提取特定字段）
kubectl get pods -o go-template --template '{{range .items}}{{.metadata.name}}{{"\n"}}{{end}}'
```

---

## 5. 部署第一个应用

### 5.1 前置条件

- 已安装 Minikube 并启动集群（`minikube start`）
- 已安装 kubectl

```bash
# 确认 kubectl 能连接集群
kubectl version

# 查看可用节点
kubectl get nodes
```

### 5.2 使用命令行创建 Deployment

```bash
kubectl create deployment kubernetes-bootcamp --image=gcr.io/google-samples/kubernetes-bootcamp:v1
```

这个命令做了以下几件事：
1. 搜索合适的节点来运行应用实例
2. 将应用调度到该节点
3. 配置集群在需要时重新调度实例

**参数说明**:

| 参数 | 说明 |
|------|------|
| `create deployment` | 创建 Deployment 资源 |
| `kubernetes-bootcamp` | Deployment 名称 |
| `--image=...` | 容器镜像地址（包括仓库 URL） |

### 5.3 查看 Deployment

```bash
kubectl get deployments
```

输出：
```
NAME                  READY   UP-TO-DATE   AVAILABLE   AGE
kubernetes-bootcamp   1/1     1            1           30s
```

**字段说明**:

| 字段 | 说明 |
|------|------|
| NAME | Deployment 名称 |
| READY | 当前就绪副本数 / 期望副本数 |
| UP-TO-DATE | 已更新到期望状态的副本数 |
| AVAILABLE | 可用副本数 |
| AGE | 运行时间 |

### 5.4 查看 Pod

```bash
kubectl get pods
```

输出：
```
NAME                                   READY   STATUS    RESTARTS   AGE
kubernetes-bootcamp-77b4f7f7d4-9p2xk   1/1     Running   0          1m
```

```bash
# 宽输出，显示更多信息
kubectl get pods -o wide
```

输出：
```
NAME                                   READY   STATUS    RESTARTS   AGE   IP           NODE
kubernetes-bootcamp-77b4f7f7d4-9p2xk   1/1     Running   0          1m   172.17.0.4   minikube
```

### 5.5 查看 ReplicaSet

```bash
kubectl get rs
```

输出：
```
NAME                             DESIRED   CURRENT   READY   AGE
kubernetes-bootcamp-77b4f7f7d4   1         1         1       2m
```

> ReplicaSet 名称格式：`[DEPLOYMENT-NAME]-[RANDOM-STRING]`

---

## 6. 查看部署状态

### 6.1 查看 Deployment 详情

```bash
kubectl describe deployment kubernetes-bootcamp
```

输出关键字段：
```
Name:                   kubernetes-bootcamp
Namespace:              default
Replicas:               1 desired | 1 updated | 1 total | 1 available | 0 unavailable
StrategyType:           RollingUpdate
  RollingUpdateStrategy: 25% max unavailable, 25% max surge
Pod Template:
  Containers:
   kubernetes-bootcamp:
    Image:              gcr.io/google-samples/kubernetes-bootcamp:v1
    Port:               <none> Host Port:  <none>
Conditions:
  Type           Status  Reason
  ----           ------  ------
  Available      True    MinimumReplicasAvailable
  Progressing    True    NewReplicaSetAvailable
```

### 6.2 查看 Pod 详情

```bash
kubectl describe pods
```

输出关键字段：
```
Name:         kubernetes-bootcamp-77b4f7f7d4-9p2xk
Namespace:    default
Node:         minikube/192.168.49.2
Status:       Running
IP:           172.17.0.4
Containers:
  kubernetes-bootcamp:
    Image:          gcr.io/google-samples/kubernetes-bootcamp:v1
    Port:           <none> Host Port:  <none>
    State:          Running
    Ready:          True
    Restart Count:  0
Events:
  Type    Reason     Age   From               Message
  ----    ------     ----  ----               -------
  Normal  Scheduled  2m    default-scheduler  Successfully assigned default/kubernetes-bootcamp...
  Normal  Pulling    2m    kubelet            Pulling image "gcr.io/google-samples/kubernetes-bootcamp:v1"
  Normal  Pulled     1m    kubelet            Successfully pulled image
  Normal  Created    1m    kubelet            Created container kubernetes-bootcamp
  Normal  Started    1m    kubelet            Started container kubernetes-bootcamp
```

---

## 7. 通过代理访问应用

### 7.1 为什么需要代理

Pod 运行在 Kubernetes 集群内部的**私有隔离网络**中：
- 默认只能被集群内的其他 Pod 和 Service 访问
- 外部网络无法直接访问

`kubectl proxy` 命令可以创建一个代理，将本地通信转发到集群内部的私有网络。

### 7.2 启动代理

**在第二个终端窗口运行**：

```bash
kubectl proxy
```

输出：
```
Starting to serve on 127.0.0.1:8001
```

### 7.3 通过代理访问 API

```bash
# 查看版本信息
curl http://localhost:8001/version

# 获取 Pod 名称
export POD_NAME=$(kubectl get pods -o go-template --template '{{range .items}}{{.metadata.name}}{{"\n"}}{{end}}')
echo "Pod Name: $POD_NAME"

# 通过代理访问 Pod
curl http://localhost:8001/api/v1/namespaces/default/pods/$POD_NAME:8080/proxy/
```

输出：
```
Hello Kubernetes bootcamp! | Running on: kubernetes-bootcamp-77b4f7f7d4-9p2xk | v=1
```

> 要在不使用代理的情况下访问应用，需要创建 Service（将在模块 4 介绍）。

---

## 8. YAML 方式创建 Deployment

### 8.1 Deployment YAML 结构

```yaml
apiVersion: apps/v1          # API 版本
kind: Deployment             # 资源类型
metadata:                    # 元数据
  name: nginx-deployment     # Deployment 名称
  labels:                    # 标签
    app: nginx
spec:                        # 期望状态
  replicas: 3                # 副本数
  selector:                  # 选择器，匹配 Pod 标签
    matchLabels:
      app: nginx
  strategy:                  # 更新策略
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 25%          # 更新时最多超出期望副本数的比例
      maxUnavailable: 25%    # 更新时最多不可用副本的比例
  template:                  # Pod 模板
    metadata:
      labels:
        app: nginx
    spec:
      containers:            # 容器定义
      - name: nginx          # 容器名称
        image: nginx:1.25    # 镜像
        ports:
        - containerPort: 80  # 容器端口
        resources:           # 资源限制
          requests:          # 请求量（调度依据）
            cpu: "100m"
            memory: "128Mi"
          limits:            # 上限量
            cpu: "200m"
            memory: "256Mi"
        livenessProbe:       # 存活探针
          httpGet:
            path: /
            port: 80
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:      # 就绪探针
          httpGet:
            path: /
            port: 80
          initialDelaySeconds: 5
          periodSeconds: 5
```

### 8.2 使用 YAML 创建

```bash
# 创建
kubectl apply -f nginx-deployment.yaml

# 查看
kubectl get deployments
kubectl get pods -o wide
```

### 8.3 命令行 vs YAML

| 方式 | 优点 | 缺点 | 适用场景 |
|------|------|------|----------|
| `kubectl create` | 快速简单 | 功能有限，不可版本控制 | 快速测试 |
| YAML 文件 | 功能完整，可版本控制 | 需要编写文件 | 生产环境 |

---

## 9. 镜像管理最佳实践

### 9.1 镜像地址格式

```
# Docker Hub
nginx:1.25
library/nginx:1.25

# 私有仓库
registry.example.com/myapp:v1.0

# Google Container Registry (GCR)
gcr.io/google-samples/kubernetes-bootcamp:v1

# GitHub Container Registry
ghcr.io/owner/image:tag
```

### 9.2 镜像拉取策略

```yaml
spec:
  containers:
  - name: app
    image: myapp:v1
    imagePullPolicy: IfNotPresent  # 默认值，本地有就不拉
    # Always: 每次都拉取最新
    # Never: 从不拉取，只用本地镜像
```

### 9.3 镜像拉取凭证

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: registry-secret
type: kubernetes.io/dockerconfigjson
data:
  .dockerconfigjson: <base64-encoded-config>
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: myapp
spec:
  template:
    spec:
      imagePullSecrets:
      - name: registry-secret
      containers:
      - name: app
        image: registry.example.com/myapp:v1
```

```bash
# 创建拉取凭证
kubectl create secret docker-registry registry-secret \
  --docker-server=registry.example.com \
  --docker-username=user \
  --docker-password=password \
  --docker-email=user@example.com
```

---

## 10. Deployment 生命周期管理

### 10.1 更新 Deployment

```bash
# 更新镜像版本
kubectl set image deployment/kubernetes-bootcamp \
  kubernetes-bootcamp=jocatalin/kubernetes-bootcamp:v2

# 更新副本数
kubectl scale deployment/kubernetes-bootcamp --replicas=4

# 编辑 Deployment 配置
kubectl edit deployment kubernetes-bootcamp
```

### 10.2 查看更新状态

```bash
# 查看滚动更新状态
kubectl rollout status deployment/kubernetes-bootcamp

# 查看更新历史
kubectl rollout history deployment/kubernetes-bootcamp

# 查看特定版本详情
kubectl rollout history deployment/kubernetes-bootcamp --revision=2
```

### 10.3 回滚

```bash
# 回滚到上一版本
kubectl rollout undo deployment/kubernetes-bootcamp

# 回滚到指定版本
kubectl rollout undo deployment/kubernetes-bootcamp --to-revision=2
```

### 10.4 删除 Deployment

```bash
# 删除 Deployment
kubectl delete deployment kubernetes-bootcamp

# 删除所有资源
kubectl delete all --all
```

---

## 11. 常见问题排查

### 11.1 Pod 状态为 ImagePullBackOff

```bash
# 查看详情
kubectl describe pod <pod-name>
```

**原因**: 镜像不存在或无法拉取

**解决**:
```bash
# 检查镜像名称是否正确
# 检查网络是否可达
# 检查镜像拉取凭证
```

### 11.2 Pod 状态为 CrashLoopBackOff

**原因**: 容器启动后崩溃

**解决**:
```bash
# 查看日志
kubectl logs <pod-name>
kubectl logs <pod-name> --previous  # 查看崩溃前的日志

# 检查应用配置
kubectl describe pod <pod-name>
```

### 11.3 Pod 一直处于 Pending

```bash
kubectl describe pod <pod-name>
```

**原因**: 资源不足或调度约束无法满足

**解决**:
```bash
# 查看节点资源
kubectl describe nodes

# 减少资源请求
# 增加节点
# 检查 nodeSelector / affinity 约束
```

### 11.4 Pod 一直处于 ContainerCreating

**原因**: 镜像拉取慢、存储挂载失败、CNI 问题

**解决**:
```bash
kubectl describe pod <pod-name>
# 查看 Events 部分，关注具体卡在哪一步
```

---

## 12. 小结与下一步

### 核心知识点回顾

1. **Deployment** 是管理应用的核心控制器，提供自愈和版本管理
2. **Pod** 是 K8S 最小部署单元，包含一个或多个容器
3. **ReplicaSet** 由 Deployment 创建，负责维持副本数
4. **kubectl** 是与集群交互的核心工具
5. Pod 运行在私有网络中，需要 Service 或 proxy 才能外部访问

### 关键命令速查

```bash
kubectl create deployment <name> --image=<image>  # 创建 Deployment
kubectl get deployments                           # 查看 Deployment
kubectl get pods -o wide                          # 查看 Pod
kubectl get rs                                    # 查看 ReplicaSet
kubectl describe deployment <name>                # 查看详情
kubectl proxy                                     # 启动代理
kubectl delete deployment <name>                  # 删除 Deployment
```

### 下一步

- [探索应用：Pod 与 Node 详解](K8S技术文档-03-探索应用Pod与Node详解.md)
- [Kubernetes 官方 Deployment 文档](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/)

---

> **参考资料**:
> - [Kubernetes 官方教程 - Deploy an App](https://kubernetes.io/docs/tutorials/kubernetes-basics/deploy-app/deploy-intro/)
> - [Kubernetes 官方 Deployment 概念](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/)
> - [Kubernetes 官方 Pod 概念](https://kubernetes.io/docs/concepts/workloads/pods/)
> - [Kubernetes 官方 kubectl 参考](https://kubernetes.io/docs/reference/kubectl/)
