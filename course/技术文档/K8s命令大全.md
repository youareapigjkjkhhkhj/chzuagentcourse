Kubernetes (K8s) 的主要命令行工具是 `kubectl`。以下是一些最常用和基础的操作命令，按功能分类：

### 1. 集群信息与状态
*   `kubectl cluster-info`：显示集群的控制平面地址和其他重要服务。
*   `kubectl version`：显示 kubectl 和服务器端版本信息。
*   `kubectl get nodes`：列出集群中的所有节点。
*   `kubectl describe node <node-name>`：查看特定节点的详细信息和事件。

### 2. 资源查看
*   `kubectl get pods`：列出当前命名空间中的所有 Pod。
    *   `-n <namespace>`：指定命名空间。
    *   `--all-namespaces` 或 `-A`：列出所有命名空间中的 Pod。
    *   `-o wide`：显示更多列信息（如节点 IP、Pod IP）。
    *   `-o yaml`：以 YAML 格式输出。
*   `kubectl get deployments`：列出所有 Deployment。
*   `kubectl get services`：列出所有 Service。
*   `kubectl get namespaces` 或 `kubectl get ns`：列出所有命名空间。
*   `kubectl get events`：列出当前命名空间中的事件。
*   `kubectl get all`：一次性列出当前命名空间中的所有资源（pod, svc, deployment, replicaset 等）。

### 3. 查看详细信息
*   `kubectl describe pod <pod-name>`：查看 Pod 的详细信息、事件、日志错误等（**排查问题必备**）。
*   `kubectl logs <pod-name>`：查看 Pod 中容器的标准输出日志。
    *   `-f`：实时跟踪日志（类似于 `tail -f`）。
    *   `-c <container-name>`：如果 Pod 中有多个容器，指定要查看的容器。
    *   `--previous`：查看上一次崩溃容器的日志。
*   `kubectl describe <resource-type> <resource-name>`：查看任何资源类型的详细信息和事件。

### 4. 执行与调试
*   `kubectl exec -it <pod-name> -- /bin/bash`：进入 Pod 中的容器执行 shell。
    *   如果容器没有 bash，可以尝试 `/bin/sh`。
    *   如果 Pod 有多个容器，用 `-c <container-name>` 指定。
*   `kubectl exec -it <pod-name> -- /bin/sh`：进入 Pod 执行 sh shell。

### 5. 资源创建与删除
*   `kubectl apply -f <filename.yaml>`：创建或更新资源（**最推荐的方式**）。
    *   `--dry-run=client`：只验证，不实际创建。
*   `kubectl create -f <filename.yaml>`：创建资源（如果资源已存在会失败）。
*   `kubectl delete -f <filename.yaml>`：删除资源。
*   `kubectl delete pod <pod-name>`：删除指定的 Pod。
*   `kubectl delete deployment <deployment-name>`：删除指定的 Deployment。
*   `kubectl delete --all`：删除当前命名空间中的所有资源（**非常危险，慎用**）。

### 6. 部署与滚动更新
*   `kubectl expose deployment <deployment-name> --port=80 --type=NodePort`：为 Deployment 创建 Service。
*   `kubectl scale deployment <deployment-name> --replicas=3`：将 Deployment 的副本数缩放为 3。
*   `kubectl rollout status deployment <deployment-name>`：检查 Deployment 的滚动更新状态。
*   `kubectl rollout history deployment <deployment-name>`：查看 Deployment 的历史记录。
*   `kubectl rollout undo deployment <deployment-name>`：回滚 Deployment 到上一个版本。
*   `kubectl set image deployment/<deployment-name> <container-name>=<new-image>`：更新 Deployment 中容器的镜像。

### 7. 配置与上下文
*   `kubectl config view`：查看当前的 kubeconfig 配置。
*   `kubectl config use-context <context-name>`：切换当前的集群上下文（多集群环境常用）。
*   `kubectl config set-context <context-name>`：设置默认上下文。

### 8. 端口转发（本地调试）
*   `kubectl port-forward <resource-type>/<resource-name> <local-port>:<remote-port>`
    *   例如：`kubectl port-forward svc/my-service 8080:80`
    *   这会在本地 8080 端口转发到服务 my-service 的 80 端口，方便在本地浏览器或 Postman 中测试。

### 9. 自动补全与帮助
*   `kubectl completion bash`：生成 bash 自动补全脚本。
*   `kubectl help`：显示所有命令的帮助信息。
*   `kubectl <command> --help`：查看特定命令的详细帮助。

### 常用别名
*   `kubectl get pods -n <namespace>` 可以简写为 `kubectl get po -n <namespace>`
*   `kubectl get services` 可以简写为 `kubectl get svc`
*   `kubectl get namespaces` 可以简写为 `kubectl get ns`
*   `kubectl get deployments` 可以简写为 `kubectl get deploy`
*   `kubectl get replicaset` 可以简写为 `kubectl get rs`

掌握这些基础命令，你可以完成绝大部分的日常运维、调试和问题排查工作。