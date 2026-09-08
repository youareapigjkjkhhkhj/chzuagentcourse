# 通过 Service 对外暴露应用

> **对应官方模块**: [Expose your app publicly](https://kubernetes.io/docs/tutorials/kubernetes-basics/expose/expose-intro/)
> **文档定位**: Service、NodePort / LoadBalancer 等

---

## 目录

- [1. Service 核心概念](#1-service-核心概念)
- [2. Service 工作原理](#2-service-工作原理)
- [3. Service 四种类型](#3-service-四种类型)
- [4. 标签与选择器](#4-标签与选择器)
- [5. 实战：创建 Service 暴露应用](#5-实战创建-service-暴露应用)
- [6. Service YAML 详解](#6-service-yaml-详解)
- [7. Endpoints 与 EndpointSlices](#7-endpoints-与-endpointslices)
- [8. Headless Service](#8-headless-service)
- [9. Ingress 入口路由](#9-ingress-入口路由)
- [10. CoreDNS 服务发现](#10-coredns-服务发现)
- [11. NetworkPolicy 网络策略](#11-networkpolicy-网络策略)
- [12. 生产环境最佳实践](#12-生产环境最佳实践)
- [13. 小结与下一步](#13-小结与下一步)

---

## 1. Service 核心概念

### 1.1 为什么需要 Service

Kubernetes Pod 是**短暂的（mortal）**——它们有生命周期，会创建也会消亡：

```
场景: 后端有 3 个 Pod 副本

Pod A (10.0.1.1) ← 哪个 IP 给前端用？
Pod B (10.0.1.2) ← Pod 重建后 IP 会变
Pod C (10.0.1.3) ← 前端不应该关心具体哪个 Pod
```

**问题**:
- Pod 有独立 IP，但 Pod 重建后 IP 会变
- 前端不应该知道后端有多少 Pod、IP 是什么
- 需要负载均衡将流量分发到多个 Pod

**Service 的作用**：提供一个**稳定的访问入口**（固定 IP + DNS 名称），将流量负载均衡到后端 Pod。

```
           ┌──────────────────┐
           │  Service         │
           │  IP: 10.96.0.10  │  ← 稳定不变
           │  DNS: myapp      │  ← 稳定不变
           └────────┬─────────┘
                    │ 负载均衡
       ┌────────────┼────────────┐
       ▼            ▼            ▼
   ┌────────┐  ┌────────┐  ┌────────┐
   │ Pod A  │  │ Pod B  │  │ Pod C  │
   │10.0.1.1│  │10.0.1.2│  │10.0.1.3│  ← IP 可能变化
   └────────┘  └────────┘  └────────┘
```

### 1.2 Service 定义

Service 是一个抽象层，定义了**一组 Pod 的逻辑集合**和**访问策略**。它通过**标签选择器（Label Selector）**来确定哪些 Pod 属于这个 Service。

```yaml
apiVersion: v1
kind: Service
metadata:
  name: my-service
spec:
  selector:           # 标签选择器：匹配标签 app=myapp 的 Pod
    app: myapp
  ports:
  - port: 80          # Service 端口
    targetPort: 8080  # Pod 端口
    protocol: TCP
```

---

## 2. Service 工作原理

### 2.1 流量转发机制

```
客户端请求
    ↓
Service ClusterIP (虚拟 IP)
    ↓
kube-proxy (节点上的网络规则)
    ↓
iptables / IPVS / eBPF 规则
    ↓ 负载均衡
后端 Pod (通过 Endpoints 维护列表)
```

### 2.2 kube-proxy 工作模式

| 模式 | 原理 | 优点 | 适用场景 |
|------|------|------|----------|
| iptables（默认） | 用 iptables DNAT 规则转发 | 轻量，内核原生 | 通用场景 |
| IPVS | 用 IPVS 负载均衡 | 高性能，算法丰富 | 大规模集群 |
| eBPF | 用 eBPF 程序处理 | 性能最佳，可观测性强 | Cilium/Calico 环境 |

### 2.3 IPVS 支持的负载均衡算法

```
rr      - 轮询（Round Robin）
lc      - 最少连接数（Least Connection）
dh      - 目标地址哈希
sh      - 源地址哈希
sed     - 最短期望延迟
nq      - 永不排队
```

---

## 3. Service 四种类型

### 3.1 类型对比

```
┌──────────────────────────────────────────────────────────┐
│                    Service 类型层级                       │
│                                                          │
│  ClusterIP (默认)                                        │
│  └─ 集群内部访问                                         │
│                                                          │
│     NodePort                                             │
│     └─ 集群外部访问 (NodeIP:Port)                        │
│        └─ 包含 ClusterIP                                 │
│                                                          │
│           LoadBalancer                                   │
│           └─ 云负载均衡器                                │
│              └─ 包含 NodePort + ClusterIP                │
│                                                          │
│  ExternalName (独立)                                     │
│  └─ DNS CNAME 映射外部服务                               │
└──────────────────────────────────────────────────────────┘
```

### 3.2 ClusterIP（默认）

**特点**: 仅集群内部可访问，分配集群内部虚拟 IP

```
集群内部:
  Pod A → ClusterIP:10.96.0.10:80 → Pod B, Pod C
```

```yaml
apiVersion: v1
kind: Service
metadata:
  name: backend-service
spec:
  type: ClusterIP          # 默认值，可省略
  selector:
    app: backend
  ports:
  - port: 80               # Service 端口
    targetPort: 8080       # Pod 端口
    protocol: TCP
```

**适用场景**: 微服务内部通信、数据库访问

### 3.3 NodePort

**特点**: 在每个节点上开放端口（30000-32767），外部可访问

```
外部客户端:
  → NodeIP:30080 → ClusterIP → Pod
```

```yaml
apiVersion: v1
kind: Service
metadata:
  name: my-service
spec:
  type: NodePort
  selector:
    app: myapp
  ports:
  - port: 80               # Service 端口（集群内部）
    targetPort: 8080       # Pod 端口
    nodePort: 30080        # 节点端口（30000-32767，可选自动分配）
```

**适用场景**: 开发测试环境、简单外部访问

### 3.4 LoadBalancer

**特点**: 云厂商自动创建外部负载均衡器，分配外部 IP

```
外部客户端:
  → 云负载均衡器 (外部 IP) → NodePort → ClusterIP → Pod
```

```yaml
apiVersion: v1
kind: Service
metadata:
  name: my-service
spec:
  type: LoadBalancer
  selector:
    app: myapp
  ports:
  - port: 80
    targetPort: 8080
  # 外部 IP 会自动分配
  # 也可指定:
  # loadBalancerIP: 203.0.113.1
```

**适用场景**: 生产环境对外提供服务（云平台）

**裸机替代方案**: MetalLB（提供 LoadBalancer 类型的裸金属实现）

### 3.5 ExternalName

**特点**: DNS CNAME 映射到外部服务，不创建代理规则

```yaml
apiVersion: v1
kind: Service
metadata:
  name: external-db
spec:
  type: ExternalName
  externalName: database.example.com
```

集群内访问 `external-db.default.svc.cluster.local` 会被解析为 `database.example.com`。

**适用场景**: 访问集群外部服务（如外部数据库），统一内部 DNS 命名

### 3.6 类型对比表

| 特性 | ClusterIP | NodePort | LoadBalancer | ExternalName |
|------|-----------|----------|--------------|--------------|
| 集群内访问 | ✅ | ✅ | ✅ | ✅ (DNS) |
| 集群外访问 | ❌ | ✅ | ✅ | ❌ |
| 外部 IP | 无 | Node IP | LB IP | CNAME |
| 端口范围 | 任意 | 30000-32767 | 任意 | N/A |
| 云依赖 | 无 | 无 | 需要 | 无 |
| 成本 | 无 | 无 | 云 LB 费用 | 无 |

---

## 4. 标签与选择器

### 4.1 标签（Labels）

标签是附加到 K8S 对象上的**键值对**，用于组织和选择资源：

```yaml
metadata:
  labels:
    app: myapp           # 应用名
    version: v1          # 版本
    environment: prod    # 环境
    tier: backend        # 层级
```

**标签使用场景**:
- 指定对象用于开发/测试/生产环境
- 嵌入版本标签
- 使用标签分类对象

### 4.2 标签操作命令

```bash
# 查看标签
kubectl get pods --show-labels

# 按标签筛选
kubectl get pods -l app=kubernetes-bootcamp
kubectl get pods -l version=v1
kubectl get services -l app=kubernetes-bootcamp

# 添加标签
kubectl label pods <pod-name> version=v1

# 更新标签
kubectl label pods <pod-name> version=v2 --overwrite

# 删除标签
kubectl label pods <pod-name> version-
```

### 4.3 标签选择器（Label Selector）

Service 通过标签选择器关联 Pod：

```yaml
spec:
  selector:
    app: kubernetes-bootcamp  # 匹配 labels.app == kubernetes-bootcamp 的 Pod
```

**选择器操作符**:

| 操作符 | 示例 | 说明 |
|--------|------|------|
| `=` / `==` | `app=nginx` | 等于 |
| `!=` | `app!=nginx` | 不等于 |
| `in` | `version in (v1, v2)` | 在集合中 |
| `notin` | `version notin (v1)` | 不在集合中 |
| `exists` | `app` | 存在该标签 |

```bash
# 命令行中使用选择器
kubectl get pods -l 'app=nginx,version=v1'
kubectl get pods -l 'environment in (prod,staging)'
kubectl get pods -l '!debug'
```

### 4.4 无选择器的 Service

某些场景下 Service 不定义 selector：
- 手动映射 Service 到特定 Endpoints
- 使用 `type: ExternalName`

```yaml
# 无选择器 Service + 手动 Endpoints
apiVersion: v1
kind: Service
metadata:
  name: external-service
spec:
  ports:
  - port: 80
---
apiVersion: v1
kind: Endpoints
metadata:
  name: external-service
subsets:
- addresses:
  - ip: 203.0.113.10
  ports:
  - port: 80
```

---

## 5. 实战：创建 Service 暴露应用

### 5.1 前置条件

确保之前部署的应用还在运行：

```bash
kubectl get pods
# 如果没有 Pod，重新创建:
# kubectl create deployment kubernetes-bootcamp --image=gcr.io/google-samples/kubernetes-bootcamp:v1
```

### 5.2 查看现有 Service

```bash
kubectl get services
```

输出：
```
NAME         TYPE        CLUSTER-IP   EXTERNAL-IP   PORT(S)   AGE
kubernetes   ClusterIP   10.96.0.1    <none>        443/TCP   30m
```

> `kubernetes` Service 是集群自带的，用于访问 API Server。

### 5.3 创建 NodePort Service

```bash
kubectl expose deployment/kubernetes-bootcamp --type="NodePort" --port 8080
```

### 5.4 查看 Service 详情

```bash
kubectl get services
```

输出：
```
NAME                  TYPE        CLUSTER-IP     EXTERNAL-IP   PORT(S)          AGE
kubernetes            ClusterIP   10.96.0.1      <none>        443/TCP          30m
kubernetes-bootcamp   NodePort    10.96.200.50   <none>        8080:31234/TCP   10s
```

```bash
kubectl describe services/kubernetes-bootcamp
```

输出：
```
Name:                     kubernetes-bootcamp
Namespace:                default
Type:                     NodePort
IP Family Policy:         SingleStack
IP Families:              IPv4
IP:                       10.96.200.50
IPs:                      10.96.200.50
Port:                     <unset>  8080/TCP
TargetPort:               8080/TCP
NodePort:                 <unset>  31234/TCP    ← 外部端口
Endpoints:                172.17.0.4:8080       ← 后端 Pod
Session Affinity:         None
External Traffic Policy:  Cluster
```

### 5.5 访问应用

```bash
# 获取 NodePort
export NODE_PORT="$(kubectl get services/kubernetes-bootcamp -o go-template='{{(index .spec.ports 0).nodePort}}')"
echo "NODE_PORT=$NODE_PORT"

# 通过节点 IP + NodePort 访问
curl http://"$(minikube ip):$NODE_PORT"
```

输出：
```
Hello Kubernetes bootcamp! | Running on: kubernetes-bootcamp-77b4f7f7d4-9p2xk | v=1
```

**Docker Desktop 驱动的特殊处理**:
```bash
# 如果使用 Docker 驱动，需要 minikube service
minikube service kubernetes-bootcamp --url
# 输出: http://127.0.0.1:51082
curl 127.0.0.1:51082
```

### 5.6 使用标签

```bash
# 查看 Deployment 自动创建的标签
kubectl describe deployment

# 按标签筛选 Pod
kubectl get pods -l app=kubernetes-bootcamp

# 按标签筛选 Service
kubectl get services -l app=kubernetes-bootcamp

# 给 Pod 添加新标签
export POD_NAME="$(kubectl get pods -o go-template --template '{{range .items}}{{.metadata.name}}{{"\n"}}{{end}}')"
kubectl label pods "$POD_NAME" version=v1

# 用新标签筛选
kubectl get pods -l version=v1
```

### 5.7 删除 Service

```bash
# 按标签删除 Service
kubectl delete service -l app=kubernetes-bootcamp

# 确认 Service 已删除
kubectl get services

# 验证外部已无法访问
curl http://"$(minikube ip):$NODE_PORT"
# 连接失败

# 验证应用仍在运行（通过 Pod 内部访问）
kubectl exec -ti $POD_NAME -- curl http://localhost:8080
# 应用仍然正常
```

> 删除 Service 不会删除 Deployment 和 Pod。要完全关闭应用需要删除 Deployment。

---

## 6. Service YAML 详解

### 6.1 完整 Service YAML

```yaml
apiVersion: v1
kind: Service
metadata:
  name: web-service
  namespace: production
  labels:
    app: web
    tier: frontend
  annotations:
    # 云负载均衡器注解（可选）
    service.beta.kubernetes.io/aws-load-balancer-type: "nlb"
spec:
  type: ClusterIP
  selector:
    app: web
    tier: frontend
  ports:
  - name: http            # 端口名称
    port: 80              # Service 端口
    targetPort: 8080      # Pod 端口（可用名称或数字）
    protocol: TCP
  - name: https
    port: 443
    targetPort: 8443
    protocol: TCP

  # 会话亲和性（有状态应用）
  sessionAffinity: ClientIP
  sessionAffinityConfig:
    clientIP:
      timeoutSeconds: 3600

  # 内部流量策略
  internalTrafficPolicy: Local   # 优先本地 Pod

  # 外部流量策略（NodePort/LoadBalancer）
  externalTrafficPolicy: Local   # 保留源 IP，只转发到本地 Pod

  # 健康检查（云 LB）
  # healthCheckNodePort: 30000
```

### 6.2 多端口 Service

```yaml
spec:
  ports:
  - name: http
    port: 80
    targetPort: http     # 引用容器端口名称
  - name: grpc
    port: 9090
    targetPort: grpc
```

---

## 7. Endpoints 与 EndpointSlices

### 7.1 Endpoints

Service 通过 Endpoints 跟踪后端 Pod 的 IP 和端口：

```bash
kubectl get endpoints
```

输出：
```
NAME                  ENDPOINTS           AGE
kubernetes            192.168.49.2:8443   1h
kubernetes-bootcamp   172.17.0.4:8080     10m
```

### 7.2 EndpointSlices（新标准）

大型集群中 Endpoints 对象过大，EndpointSlices 将其拆分为多个切片：

```bash
kubectl get endpointslices
```

**EndpointSlice 优势**:
- 每个切片最多 100 个端点
- 支持拓扑信息（节点、区域）
- 更高效的更新机制

### 7.3 就绪探针与 Endpoints

```
Pod readinessProbe 成功 → Pod IP 加入 Endpoints → Service 转发流量
Pod readinessProbe 失败 → Pod IP 移出 Endpoints → Service 停止转发
```

> 这就是就绪探针的核心作用——控制哪些 Pod 接收流量。

---

## 8. Headless Service

### 8.1 什么是 Headless Service

设置 `clusterIP: None` 的 Service，不为 Service 分配虚拟 IP，DNS 查询直接返回 Pod IP：

```yaml
apiVersion: v1
kind: Service
metadata:
  name: database-headless
spec:
  clusterIP: None      # ← 这使 Service 变为 Headless
  selector:
    app: postgres
  ports:
  - port: 5432
    targetPort: 5432
```

### 8.2 Headless Service 的 DNS 行为

```
# 普通 Service:
nslookup database.default.svc.cluster.local
→ 返回 ClusterIP (10.96.0.10)

# Headless Service:
nslookup database-headless.default.svc.cluster.local
→ 返回所有 Pod IP:
  10.0.1.1
  10.0.1.2
  10.0.1.3
```

### 8.3 适用场景

- StatefulSet（每个 Pod 需要独立 DNS 名称）
- 数据库集群（需要直连特定节点）
- 服务发现（客户端自行负载均衡）

**StatefulSet + Headless Service**:
```
pod-0.database.default.svc.cluster.local → 10.0.1.1
pod-1.database.default.svc.cluster.local → 10.0.1.2
pod-2.database.default.svc.cluster.local → 10.0.1.3
```

---

## 9. Ingress 入口路由

### 9.1 Ingress vs Service

```
传统方式 (每个服务一个 LoadBalancer):
  外部 → LB1 → Service1 → Pods
       → LB2 → Service2 → Pods
       → LB3 → Service3 → Pods
  (成本高，管理复杂)

Ingress 方式 (单个入口，按规则路由):
  外部 → 单个 LB → Ingress Controller
                    ↓ 按域名/路径路由
                    ├── /api    → Service1 → Pods
                    ├── /web    → Service2 → Pods
                    └── /admin  → Service3 → Pods
```

### 9.2 Ingress 资源定义

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: my-ingress
  annotations:
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/limit-rps: "100"
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - myapp.example.com
    secretName: my-tls-secret
  rules:
  - host: myapp.example.com
    http:
      paths:
      - path: /api
        pathType: Prefix
        backend:
          service:
            name: api-service
            port:
              number: 80
      - path: /
        pathType: Prefix
        backend:
          service:
            name: web-service
            port:
              number: 80
```

### 9.3 主流 Ingress Controller

| Controller | 特点 |
|------------|------|
| NGINX Ingress | 最流行，功能丰富 |
| Traefik | 现代，自动 Let's Encrypt |
| HAProxy | 高性能 |
| AWS ALB | AWS 原生 |
| Istio Gateway | Service Mesh 集成 |

---

## 10. CoreDNS 服务发现

### 10.1 DNS 命名规则

```
Service: <service-name>.<namespace>.svc.cluster.local
Pod:     <pod-ip-dashed>.<namespace>.pod.cluster.local

示例:
  myapp.default.svc.cluster.local          # Service
  10-244-1-5.default.pod.cluster.local     # Pod
```

### 10.2 集群内 DNS 解析

```bash
# 在 Pod 内部测试 DNS
kubectl exec -it <pod-name> -- nslookup kubernetes-bootcamp
```

```
Name:    kubernetes-bootcamp.default.svc.cluster.local
Address: 10.96.200.50
```

### 10.3 跨命名空间访问

```bash
# 同命名空间: 直接用 Service 名称
curl http://backend-service:8080

# 跨命名空间: 使用完整 DNS 名称
curl http://backend-service.production.svc.cluster.local:8080
```

---

## 11. NetworkPolicy 网络策略

### 11.1 为什么需要 NetworkPolicy

默认情况下，K8S 中所有 Pod 可以互相通信。NetworkPolicy 用于限制 Pod 间通信：

```
默认: 所有 Pod ←→ 所有 Pod (全通)

NetworkPolicy:
  Pod A ←→ Pod B (允许)
  Pod A ←×→ Pod C (拒绝)
```

### 11.2 默认拒绝所有入站流量

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-ingress
  namespace: app
spec:
  podSelector: {}          # 选中所有 Pod
  policyTypes:
  - Ingress                 # 入站策略
```

### 11.3 允许特定流量

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-web-traffic
  namespace: app
spec:
  podSelector:
    matchLabels:
      app: api
  policyTypes:
  - Ingress
  ingress:
  - from:
    # 允许来自 ingress-nginx 命名空间的流量
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: ingress-nginx
    ports:
    - protocol: TCP
      port: 8080
```

### 11.4 NetworkPolicy 实施步骤（生产推荐）

```
步骤 1: 命名空间级别 Ingress 默认拒绝
步骤 2: 放行来自 Ingress Controller 的流量
步骤 3: 放行同命名空间内服务互调
步骤 4: Egress 放行 DNS（先放行，再逐步细化）
```

> **注意**: NetworkPolicy 需要 CNI 插件支持（Calico、Cilium 等支持，Flannel 原生不支持）。

---

## 12. 生产环境最佳实践

### 12.1 Service 设计原则

1. **内部服务用 ClusterIP**，外部服务用 Ingress + ClusterIP
2. **避免直接用 NodePort** 暴露生产服务
3. **使用 readinessProbe** 确保 Endpoints 准确
4. **配置 externalTrafficPolicy: Local** 保留源 IP
5. **使用 sessionAffinity** 处理有状态会话

### 12.2 服务间通信最佳实践

```yaml
# 1. 使用命名端口
ports:
- name: http
  containerPort: 8080

# 2. Service 引用命名端口
spec:
  ports:
  - port: 80
    targetPort: http    # 引用容器端口名称，避免端口变更问题

# 3. 使用 DNS 名称访问服务
# 同命名空间: http://backend:8080
# 跨命名空间: http://backend.production:8080
```

### 12.3 Ingress 生产配置

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: production-ingress
  annotations:
    # SSL 重定向
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    # 限流
    nginx.ingress.kubernetes.io/limit-rps: "100"
    nginx.ingress.kubernetes.io/limit-connections: "50"
    # 超时
    nginx.ingress.kubernetes.io/proxy-connect-timeout: "30"
    nginx.ingress.kubernetes.io/proxy-read-timeout: "60"
    # CORS
    nginx.ingress.kubernetes.io/enable-cors: "true"
    nginx.ingress.kubernetes.io/cors-allow-origin: "https://example.com"
    # WebSocket
    nginx.ingress.kubernetes.io/configuration-snippet: |
      proxy_set_header Upgrade $http_upgrade;
      proxy_set_header Connection "upgrade";
```

### 12.4 裸金属 LoadBalancer 方案

| 方案 | 说明 |
|------|------|
| MetalLB | 裸金属 K8S 的 LoadBalancer 实现 |
| kube-vip | VIP 管理，适合小规模 |
| Porter | 基于 BGP 的 LoadBalancer |
| OpenELB | 开源企业级 LoadBalancer |

---

## 13. 小结与下一步

### 核心知识点回顾

1. **Service** 为 Pod 提供稳定的访问入口和负载均衡
2. **四种类型**: ClusterIP（内部）、NodePort（节点端口）、LoadBalancer（云 LB）、ExternalName（DNS 映射）
3. **标签与选择器** 是 Service 关联 Pod 的机制
4. **Headless Service** 不分配虚拟 IP，DNS 直接返回 Pod IP
5. **Ingress** 提供 L7 路由，支持域名和路径转发
6. **CoreDNS** 提供集群内服务发现
7. **NetworkPolicy** 控制 Pod 间网络访问

### 关键命令速查

```bash
kubectl expose deployment <name> --type=NodePort --port 8080  # 创建 Service
kubectl get services                                           # 查看 Service
kubectl describe service <name>                                # 查看详情
kubectl get endpoints                                          # 查看 Endpoints
kubectl label pods <pod-name> key=value                        # 添加标签
kubectl get pods -l key=value                                  # 按标签筛选
kubectl delete service -l app=myapp                            # 删除 Service
```

### 下一步

- [应用扩缩容实践](K8S技术文档-05-应用扩缩容实践.md)
- [Kubernetes 官方 Service 文档](https://kubernetes.io/docs/concepts/services-networking/service/)
- [Kubernetes Ingress 文档](https://kubernetes.io/docs/concepts/services-networking/ingress/)
- [Kubernetes NetworkPolicy 文档](https://kubernetes.io/docs/concepts/services-networking/network-policies/)

---

> **参考资料**:
> - [Kubernetes 官方教程 - Expose Your App](https://kubernetes.io/docs/tutorials/kubernetes-basics/expose/expose-intro/)
> - [Kubernetes 官方 Service 概念](https://kubernetes.io/docs/concepts/services-networking/service/)
> - [Kubernetes Networking Best Practices 2025](https://kubezilla.io/kubernetes-networking-best-practices-a-complete-guide-for-2025/)
> - [Networking Kubernetes Guide](https://floriancourouge.com/en/blog/kubernetes-networking-guide)
> - [Kubernetes NetworkPolicy 实战](https://www.cfncloud.com/zh/p/kubernetes-tip-networkpolicy)
