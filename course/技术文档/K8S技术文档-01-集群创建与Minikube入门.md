# Kubernetes 集群创建与 Minikube 入门

> **对应官方模块**: [Create a Kubernetes cluster](https://kubernetes.io/docs/tutorials/kubernetes-basics/create-cluster/cluster-intro/)
> **文档定位**: 讲集群概念 + 用 Minikube 本地搭建

---

## 目录

- [1. Kubernetes 概述](#1-kubernetes-概述)
- [2. 集群架构详解](#2-集群架构详解)
- [3. 控制平面组件](#3-控制平面组件)
- [4. 工作节点组件](#4-工作节点组件)
- [5. 集群插件](#5-集群插件)
- [6. Minikube 简介](#6-minikube-简介)
- [7. 环境准备与安装](#7-环境准备与安装)
- [8. 创建第一个集群](#8-创建第一个集群)
- [9. 集群操作基础命令](#9-集群操作基础命令)
- [10. 生产环境集群搭建概览](#10-生产环境集群搭建概览)
- [11. 常见问题排查](#11-常见问题排查)
- [12. 小结与下一步](#12-小结与下一步)

---

## 1. Kubernetes 概述

### 1.1 什么是 Kubernetes

Kubernetes（简称 K8S）是一个生产级的开源容器编排平台，负责在集群中**自动化部署、扩展和管理容器化应用**。它将多台计算机连接为一个统一的计算资源池，将应用以容器的方式调度到合适的节点上运行。

**核心能力**:

| 能力 | 说明 |
|------|------|
| 服务发现与负载均衡 | 为 Pod 分配独立 IP，提供 DNS 名称和负载均衡 |
| 存储编排 | 自动挂载本地存储、云存储或网络存储（NFS、iSCSI 等） |
| 自动滚动发布 | 无停机更新应用版本，支持回滚 |
| 自动装箱 | 根据资源需求自动调度容器到合适节点 |
| 自愈 | 容器崩溃自动重启，节点故障自动迁移 Pod |
| 密钥与配置管理 | 管理敏感信息和应用配置，无需重建镜像 |
| 水平/垂直扩展 | 按需增加/减少 Pod 副本或调整资源配置 |

### 1.2 为什么需要 Kubernetes

在容器编排出现之前，应用通常通过安装脚本直接部署到特定机器上，存在以下问题：

- **机器故障无法自愈**：脚本启动的应用在机器宕机后无法自动恢复
- **资源利用率低**：应用与机器绑定，无法动态调度
- **扩缩容困难**：手动增加机器和部署应用

Kubernetes 通过**声明式 API** 解决了这些问题：

```
你告诉 Kubernetes "我要 3 个 Nginx 副本"
Kubernetes 负责调度、监控、自愈、扩缩容
```

---

## 2. 集群架构详解

### 2.1 集群组成

Kubernetes 集群由两类资源组成：

```
┌─────────────────────────────────────────────────────────┐
│                   Kubernetes Cluster                     │
│                                                         │
│  ┌─────────────────────────┐                            │
│  │     Control Plane       │  ← 管理集群的大脑           │
│  │  (控制平面)              │                            │
│  │  • kube-apiserver       │                            │
│  │  • etcd                 │                            │
│  │  • kube-scheduler       │                            │
│  │  • kube-controller-mgr  │                            │
│  └────────────┬────────────┘                            │
│               │ 管理                                      │
│  ┌────────────┴────────────┐  ┌──────────────────────┐  │
│  │       Node 1            │  │       Node 2         │  │
│  │  (工作节点)              │  │  (工作节点)           │  │
│  │  • kubelet              │  │  • kubelet           │  │
│  │  • kube-proxy           │  │  • kube-proxy        │  │
│  │  • Container Runtime    │  │  • Container Runtime │  │
│  │  • Pod Pod Pod          │  │  • Pod Pod Pod       │  │
│  └─────────────────────────┘  └──────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

**控制平面**（Control Plane）负责管理整个集群：调度应用、维护期望状态、扩展应用、滚动更新等。

**节点**（Node）是运行应用的工作机器（虚拟机或物理机），每个节点都运行 Kubelet 代理与控制平面通信。

![image-20260731185821540](E:\workbuddy-study\study\images\image-20260731185821540.png)

### 2.2 控制平面与节点的交互

```
用户/kubectl  →  kube-apiserver  →  etcd (存储状态)
                        ↓
                 kube-scheduler (调度 Pod)
                        ↓
                 kube-controller-manager (调谐状态)
                        ↓
              kubelet (节点代理)  →  容器运行时 (containerd)
                        ↓
                    Pod 运行
```

当你在 Kubernetes 上部署应用时：
1. 你告诉控制平面启动应用容器
2. 控制平面将容器调度到集群中的节点上运行
3. 节点上的 kubelet 通过 Kubernetes API 与控制平面通信

### 2.3 官方架构图

> 官方架构图参考: `https://kubernetes.io/images/docs/components-of-kubernetes.svg`

![image-20260731185730523](E:\workbuddy-study\study\images\image-20260731185730523.png)

---

## 3. 控制平面组件

### 3.1 kube-apiserver（API 服务器）

**角色**: 集群的"前门"，所有操作的统一入口

**核心功能**:
- 暴露 Kubernetes API，处理所有 REST 操作
- 认证（Authentication）、授权（Authorization，RBAC）
- 准入控制（Admission Control，包括 Mutating 和 Validating Webhook）
- 唯一可以直接读写 etcd 的组件
- 支持水平扩展（多实例 + 负载均衡）

**请求处理流水线**:

```
请求 → TLS → 认证 → 授权 → 准入控制(Mutating) → 持久化到 etcd → 准入控制(Validating) → 响应
```

**验证 API 可用**:

```bash
# 查看集群版本
kubectl version

# 查看 API 资源列表
kubectl api-resources

# 直接访问 API（通过 proxy）
kubectl proxy &
curl http://localhost:8001/version
```

### 3.2 etcd（分布式键值存储）

**角色**: 集群的"唯一真相源"（Single Source of Truth）

**核心特性**:

| 特性 | 说明 |
|------|------|
| 强一致性 | 基于 Raft 协议，写入需要多数节点同意 |
| 高可用 | 生产环境建议 3 或 5 节点部署 |
| 数据存储 | Pod 配置、Service 规则、Secret 等所有集群状态 |
| 仅 API Server 可直接访问 | 其他组件通过 API Server 间接读写 |

**数据路径示例**: `/registry/pods/<namespace>/<pod-name>`

**生产环境要点**:
- 定期备份 etcd 快照
- 开启静态加密（Encryption at Rest）
- 监控 etcd 延迟和磁盘 IO

```bash
# etcd 快照备份（生产环境必需）
ETCDCTL_API=3 etcdctl snapshot save backup.db \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key
```

### 3.3 kube-scheduler（调度器）

**角色**: 集群的"匹配员"，决定 Pod 运行在哪个节点

**调度决策因素**:
- 资源需求（CPU / 内存 / GPU）
- 亲和性 / 反亲和性（Affinity / Anti-Affinity）
- 污点 / 容忍（Taints / Tolerations）
- 节点选择器（NodeSelector）
- 数据局部性（Data Locality）
- 拓扑分布约束（Topology Spread Constraints）

**调度流程**:

```
新 Pod 创建 (无节点分配)
       ↓
   过滤阶段 (Filter)
   排除不满足资源/约束的节点
       ↓
   评分阶段 (Score)
   对剩余节点打分排序
       ↓
   绑定阶段 (Bind)
   将 Pod 绑定到得分最高的节点
```

> 调度器只做决策，不负责启动 Pod（由 kubelet 执行）。

### 3.4 kube-controller-manager（控制器管理器）

**角色**: 集群的"自动化引擎"，运行多种控制器

**内置控制器**:

| 控制器 | 功能 |
|--------|------|
| ReplicaSet 控制器 | 维持 Pod 副本数 |
| Deployment 控制器 | 管理 Pod 滚动升级和回滚 |
| Node 控制器 | 监控节点健康状态 |
| Endpoints 控制器 | 关联 Service 与 Pod |
| ServiceAccount 控制器 | 创建默认账户和 API Token |
| Job 控制器 | 管理批处理任务 |

**调谐机制（Reconciliation Loop）**:

```
     期望状态 (Desired)          实际状态 (Current)
          ↓                          ↓
          └──────── 比较差异 ────────┘
                    ↓
              差异 → 执行操作
              (创建/删除/更新 Pod)
                    ↓
              再次比较 (持续循环)
```

### 3.5 cloud-controller-manager（云控制器管理器）

**角色**: 连接 Kubernetes 与云服务商 API 的桥梁

**功能**: 管理负载均衡器、存储卷、节点注册、路由创建等

> 仅在云环境（AWS、Azure、GCP、阿里云等）中部署，裸机/私有集群不需要。

---

## 4. 工作节点组件

### 4.1 kubelet（节点代理）

**角色**: 每个节点上的"代理人"，负责管理本节点的 Pod

**核心职责**:
- 从 API Server 获取分配到本节点的 Pod 规格（PodSpec）
- 调用容器运行时（containerd/CRI-O）启动/停止容器
- 执行容器健康检查（Probe）
- 定期向 API Server 上报节点和 Pod 状态
- 管理卷（Volume）的挂载/卸载
- 执行静态 Pod（Static Pod，`/etc/kubernetes/manifests/` 目录下的 Pod）

```
API Server ──→ kubelet ──→ 容器运行时 (containerd)
                  ↓                    ↓
              执行 Probe          拉取镜像、运行容器
                  ↓
              上报状态 ──→ API Server ──→ etcd
```

### 4.2 kube-proxy（网络代理）

**角色**: 实现 Kubernetes Service 网络功能

**核心功能**:
- 为 Service 分配虚拟 IP（ClusterIP）
- 维护节点上的网络转发规则
- 将 Service 流量负载均衡到后端 Pod

**工作模式**:

| 模式 | 特点 |
|------|------|
| iptables（默认） | 轻量，使用 iptables 规则转发 |
| IPVS | 高性能，适合大规模集群，支持更多负载均衡算法 |
| eBPF | 最新模式，通过 Cilium 等 CNI 实现更高性能 |

> 在使用 Cilium 或 Calico eBPF 模式时，kube-proxy 可以被 CNI 插件替代。

### 4.3 容器运行时（Container Runtime）

**角色**: 实际拉取镜像和运行容器的软件

**主流选项**:

| 运行时 | 说明 |
|--------|------|
| containerd | 目前主流默认选择（K8S 1.24+ 默认） |
| CRI-O | 专为 K8S 设计，轻量 |
| Docker | 已弃用直接支持，需通过 cri-dockerd 适配器 |

通过 **CRI（Container Runtime Interface）** 标准接口与 kubelet 通信。

```
kubelet ──CRI──→ containerd ──→ 容器
kubelet ──CRI──→ CRI-O ──→ 容器
```

---

## 5. 集群插件

### 5.1 CNI 网络插件

K8S 本身不提供 Pod 间跨节点通信，需要 CNI 插件实现：

| 插件 | 模式 | 特点 |
|------|------|------|
| Calico | BGP/VXLAN/IPIP | 性能优秀，支持 NetworkPolicy |
| Cilium | eBPF | 性能最佳，L7 策略，可观测性强 |
| Flannel | VXLAN/host-gw | 简单轻量，适合入门 |
| Weave | Mesh overlay | 支持加密 |

**K8S 网络模型四原则**:
1. 每个 Pod 拥有独立 IP
2. Pod 间可直接通信，无需 NAT
3. 节点上的代理可与所有 Pod 通信
4. Pod 看到的 IP 与其他 Pod 看到的一致

### 5.2 CoreDNS

为集群内的 Pod 和 Service 提供 DNS 解析：
- Service DNS: `<service-name>.<namespace>.svc.cluster.local`
- Pod DNS: `<pod-ip-dashed>.<namespace>.pod.cluster.local`

### 5.3 其他常用插件

| 插件 | 功能 |
|------|------|
| Metrics Server | 提供资源使用指标（CPU/内存），HPA 依赖 |
| Dashboard | K8S Web UI |
| Prometheus + Grafana | 监控告警 |
| Ingress Controller | HTTP/HTTPS 路由（Nginx、Traefik 等） |

---

## 6. Minikube 简介

### 6.1 什么是 Minikube

Minikube 是一个轻量级的 Kubernetes 实现，可在本地机器上创建一个 VM（或 Docker 容器）并部署一个**单节点集群**。

**特点**:
- 支持 Linux、macOS、Windows
- 提供简单的 CLI 操作（start、stop、status、delete）
- 适合开发、测试和学习
- 支持多种驱动（Docker、VirtualBox、VMware、Hyper-V 等）

### 6.2 Minikube vs 生产集群

| 对比项 | Minikube | 生产集群 |
|--------|----------|----------|
| 节点数 | 单节点 | 多节点（3+） |
| 高可用 | 不支持 | 支持（多控制平面） |
| 用途 | 开发/学习 | 生产环境 |
| 安装难度 | 简单 | 复杂（kubeadm/Rancher/云托管） |

---

## 7. 环境准备与安装

### 7.1 安装 Minikube

**Linux**:
```bash
curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64
sudo install minikube-linux-amd64 /usr/local/bin/minikube
```

**macOS**:
```bash
brew install minikube
```

**Windows**:
```powershell
choco install minikube
# 或下载 exe: https://minikube.sigs.k8s.io/docs/start/
```

### 7.2 安装 kubectl

**Linux**:
```bash
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl
```

**macOS**:
```bash
brew install kubectl
```

**Windows**:
```powershell
choco install kubernetes-cli
```

### 7.3 验证安装

```bash
minikube version
kubectl version --client
```

---

## 8. 创建第一个集群

### 8.1 启动集群

```bash
minikube start
```

输出示例：
```
😄  minikube v1.33.0 on Darwin 14.0
✨  Using the docker driver based on existing profile
👍  Starting control plane node minikube in cluster minikube
🚜  Pulling base image ...
🔥  Creating docker container (CPUs=2, Memory=4000MB) ...
🐳  Preparing Kubernetes v1.31.0 on Docker 27.1.1 ...
    ▪ Generating certificates and keys ...
    ▪ Booting up control plane ...
    ▪ Configuring RBAC rules ...
🔗  Configuring bridge CNI (Container Networking Interface) ...
🔎  Verifying Kubernetes components...
    ▪ Using image gcr.io/k8s-minikube/storage-provisioner:v5
🌟  Enabled addons: storage-provisioner, default-storageclass
🏄  Done! kubectl is now configured to use "minikube" cluster
```

**自定义配置启动**:
```bash
# 指定 K8S 版本
minikube start --kubernetes-version=v1.31.0

# 指定资源
minikube start --cpus=4 --memory=8192

# 指定驱动
minikube start --driver=virtualbox

# 多节点集群
minikube start --nodes=3
```

### 8.2 验证集群状态

```bash
# 查看 Minikube 状态
minikube status

# 输出:
# minikube
# type: Control Plane
# host: Running
# kubelet: Running
# apiserver: Running
# kubeconfig: Configured
```

```bash
# 查看集群信息
kubectl cluster-info

# 输出:
# Kubernetes control plane is running at https://127.0.0.1:6443
# CoreDNS is running at https://127.0.0.1:6443/api/v1/namespaces/kube-system/services/kube-dns:dns/proxy
```

```bash
# 查看节点
kubectl get nodes

# 输出:
# NAME       STATUS   ROLES           AGE   VERSION
# minikube   Ready    control-plane   2m    v1.31.0
```

### 8.3 打开 Dashboard

```bash
minikube dashboard
```

这会在浏览器中打开 Kubernetes Web UI，可以可视化查看集群状态。

---

## 9. 集群操作基础命令

### 9.1 集群管理

```bash
# 查看集群信息
kubectl cluster-info

# 查看集群节点
kubectl get nodes

# 查看节点详情
kubectl describe node minikube

# 查看集群事件
kubectl get events --sort-by='.metadata.creationTimestamp'
```

### 9.2 Minikube 管理命令

```bash
# 启动集群
minikube start

# 停止集群（不删除数据）
minikube stop

# 查看状态
minikube status

# 删除集群
minikube delete

# 查看 IP
minikube ip

# SSH 到节点
minikube ssh

# 查看已安装插件
minikube addons list

# 启用插件
minikube addons enable ingress
minikube addons enable metrics-server
```

### 9.3 kubectl 命令格式

kubectl 命令的基本格式：`kubectl action resource`

```bash
# 查看 Pod 列表
kubectl get pods

# 查看 Service 列表
kubectl get services

# 查看 Deployment 列表
kubectl get deployments

# 查看所有资源
kubectl get all

# 查看详情
kubectl describe pod <pod-name>

# 查看日志
kubectl logs <pod-name>

# 在容器中执行命令
kubectl exec -it <pod-name> -- bash
```

---

## 10. 生产环境集群搭建概览

### 10.1 主流搭建方式

| 方式 | 说明 | 适用场景 |
|------|------|----------|
| 云托管 (EKS/GKE/AKS) | 云厂商管理控制平面 | 最省心，生产首选 |
| kubeadm | 官方集群初始化工具 | 自建集群标准方式 |
| Rancher / RKE | 图形化集群管理 | 企业自建 |
| K3s | 轻量级 K8S | 边缘/IoT/开发 |
| Kind | Docker 中运行 K8S | CI/CD 测试 |

### 10.2 kubeadm 快速概览

```bash
# 1. 所有节点安装容器运行时 (containerd)
# 2. 所有节点安装 kubeadm, kubelet, kubectl

# 3. 控制平面节点初始化
sudo kubeadm init --pod-network-cidr=10.244.0.0/16

# 4. 配置 kubectl
mkdir -p $HOME/.kube
sudo cp -i /etc/kubernetes/admin.conf $HOME/.kube/config
sudo chown $(id -u):$(id -g) $HOME/.kube/config

# 5. 安装 CNI 网络插件
kubectl apply -f https://raw.githubusercontent.com/projectcalico/calico/v3.26.1/manifests/calico.yaml

# 6. 工作节点加入集群
kubeadm join <control-plane-ip>:6443 --token <token> --discovery-token-ca-cert-hash <hash>
```

### 10.3 高可用集群

生产环境建议至少 3 个控制平面节点 + 3+ 个工作节点：

```
                    ┌─────────────┐
                    │  Load Balancer │
                    └──────┬──────┘
           ┌────────┬──────┴───────┬────────┐
           ▼        ▼              ▼        ▼
     ┌──────────┐ ┌──────────┐ ┌──────────┐
     │ CP Node 1│ │ CP Node 2│ │ CP Node 3│
     │ apiserver│ │ apiserver│ │ apiserver│
     │   etcd   │ │   etcd   │ │   etcd   │
     └──────────┘ └──────────┘ └──────────┘
           │            │            │
     ┌─────┴────┐ ┌─────┴────┐ ┌─────┴────┐
     │ Worker 1 │ │ Worker 2 │ │ Worker 3 │
     │ Pod Pod  │ │ Pod Pod  │ │ Pod Pod  │
     └──────────┘ └──────────┘ └──────────┘
```

---

## 11. 常见问题排查

### 11.1 Minikube 启动失败

```bash
# 查看详细日志
minikube logs

# 常见原因：
# 1. Docker 未启动 → 启动 Docker Desktop
# 2. 资源不足 → 增加内存/CPU
# 3. 驱动冲突 → 清理后重新指定驱动

minikube delete
minikube start --driver=docker --cpus=4 --memory=8192
```

### 11.2 节点 NotReady

```bash
# 查看节点详情，关注 Events 和 Conditions
kubectl describe node <node-name>

# 常见原因：
# 1. CNI 插件未安装 → Pod 无法获取 IP
# 2. kubelet 未运行 → systemctl status kubelet
# 3. 磁盘空间不足 → df -h
```

### 11.3 kubectl 无法连接集群

```bash
# 检查 kubeconfig
kubectl config view

# 检查当前上下文
kubectl config current-context

# 检查 API Server 是否可达
kubectl cluster-info

# 常见修复：
# 1. Minikube 未启动 → minikube start
# 2. kubeconfig 配置错误 → 重新生成
# 3. 证书过期 → 更新证书
```

### 11.4 CoreDNS 问题

```bash
# 查看 CoreDNS Pod 状态
kubectl get pods -n kube-system -l k8s-app=kube-dns

# 查看 CoreDNS 日志
kubectl logs -n kube-system -l k8s-app=kube-dns

# 常见原因：
# 1. CNI 未正确安装
# 2. CoreDNS ConfigMap 配置错误
# 3. 节点 DNS 解析问题
```

---

## 12. 小结与下一步

### 核心知识点回顾

1. **K8S 集群** = 控制平面（管理） + 工作节点（执行）
2. **控制平面** = API Server + etcd + Scheduler + Controller Manager
3. **工作节点** = Kubelet + Kube-proxy + 容器运行时
4. **Minikube** 是本地学习 K8S 的最佳工具
5. **kubectl** 是与集群交互的核心命令行工具

### 下一步

- [使用 Deployment 部署第一个应用](K8S技术文档-02-使用Deployment部署第一个应用.md)
- [Kubernetes 官方集群架构文档](https://kubernetes.io/docs/concepts/architecture/)
- [Minikube 官方文档](https://minikube.sigs.k8s.io/docs/)

---

> **参考资料**:
> - [Kubernetes 官方教程 - Create a Cluster](https://kubernetes.io/docs/tutorials/kubernetes-basics/create-cluster/cluster-intro/)
> - [Kubernetes 官方架构文档](https://kubernetes.io/docs/concepts/architecture/)
> - [12 Must-Know Kubernetes Architecture Components](https://www.devopstraininginstitute.com/blog/12-must-know-kubernetes-architecture-components)
> - [The Illustrated Guide to the Kubernetes Control Plane](https://sealos.io/blog/the-illustrated-guide-to-the-kubernetes-control-plane)
> - [10 张图说透 Kubernetes 架构和数据流](https://flashcat.cloud/blog/kubernetes-architecture-explained)
