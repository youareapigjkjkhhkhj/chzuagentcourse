# 消息队列 (MQ) 技术文档大全

> **版本**: 2025 年最新整理 | **覆盖产品**: Kafka / RabbitMQ / RocketMQ | **适用对象**: 后端开发 / 架构师 / 运维工程师
>
> 本文档全面覆盖消息队列的核心概念、架构原理、三大主流产品对比、Spring Boot 集成实战、消息可靠性保障、高级特性及运维监控，力求成为一份"M 次查阅，终身受益"的消息中间件工程参考手册。

---

## 目录

- [一、消息队列概述与核心概念](#一消息队列概述与核心概念)
- [二、消息通信模型](#二消息通信模型)
- [三、主流 MQ 全面对比与选型](#三主流-mq-全面对比与选型)
- [四、Apache Kafka 详解](#四apache-kafka-详解)
- [五、RabbitMQ 详解](#五rabbitmq-详解)
- [六、Apache RocketMQ 详解](#六apache-rocketmq-详解)
- [七、Spring Boot 集成实战](#七spring-boot-集成实战)
- [八、消息可靠性保障](#八消息可靠性保障)
- [九、消息幂等性](#九消息幂等性)
- [十、消息顺序性](#十消息顺序性)
- [十一、消���积压处理](#十一消息积压处理)
- [十二、事务消息与分布式事务](#十二事务消息与分布式事务)
- [十三、死信队列与延迟队列](#十三死信队列与延迟队列)
- [十四、运维监控与故障排查](#十四运维监控与故障排查)
- [十五、开发最佳实践与避坑指南](#十五开发最佳实践与避坑指南)
- [附录：参考资料](#附录参考资料)

---

## 一、消息队列概述与核心概念

### 1.1 什么是消息队列

消息队列 (Message Queue, MQ) 是分布式系统中实现**异步通信**的中间件，它在生产者和消费者之间充当"缓冲层"，实现系统解耦、异步处理和流量削峰。

**生活类比 — 快递驿站**：

```
寄件人(生产者) → 驿站(消息队列) → 快递员(消费者)
    │                  │                  │
    │                  │                  │
  寄包裹           暂存包裹           取件配送
```

- **寄件人**不需要知道快递员是谁、什么时候来取件
- **驿站**作为中间缓冲，暂存包裹
- **快递员**按自己的节奏取件配送

### 1.2 为什么需要消息队列

**没有 MQ 的痛点**：

```
订单服务 ──同步调用──▶ 库存服务
    │                    │
    ├──同步调用─────────▶ 支付服务
    │                    │
    └──同步调用─────────▶ 物流服务

问题：
1. 耦合度高：任一服务故障，整个链路失败
2. 流量冲击：秒杀时 10 万个请求直接打到数据库
3. 体验差：发短信阻塞，用户也要等待
```

**有 MQ 之后**：

```
订单服务 ──异步投递──▶  [Message Queue] ──消费──▶ 库存服务
                        │                        │
                        ├──消费─────────────────▶ 支付服务
                        │                        │
                        └──消费─────────────────▶ 物流服务
```

### 1.3 核心角色

| 角色 | 说明 | 类比 |
|------|------|------|
| **消息 (Message)** | 传递的数据单元，包含消息体(Payload)和消息头(Headers) | 包裹 |
| **生产者 (Producer)** | 发送消息的应用程序 | 寄件人 |
| **消费者 (Consumer)** | 接收并处理消息的应用程序 | 收件人/快递员 |
| **Broker (消息代理)** | 消息中间件服务器，负责存储、路由和转发消息 | 驿站 |
| **主题 (Topic)** | 消息的分类标签，类似"频道" | 快递分区 |
| **队列 (Queue)** | 消息的存储容器（点对点模式） | 货架 |

### 1.4 MQ 的核心价值

| 价值 | 说明 | 典型场景 |
|------|------|----------|
| **系统解耦** | 服务间通过消息通信，不直接依赖 | 订单完成后通知各系统 |
| **异步处理** | 耗时操作异步化，提升响应速度 | 注册后发邮件/短信 |
| **流量削峰** | 缓冲瞬时高峰，保护下游系统 | 秒杀/大促活动 |
| **最终一致性** | 通过消息保证分布式数据最终一致 | 跨服务数据同步 |
| **广播通知** | 一条消息通知多个消费者 | 事件驱动架构 |

### 1.5 消息传递流程

```
生产者(Producer)               消费者(Consumer)
    │                               ▲
    │  发送消息                     │  消费消息
    ▼                               │
┌─────────────────────────────────────────────┐
│                 Broker (消息代理)             │
│  ┌─────────┐  ┌─────────┐  ┌─────────────┐  │
│  │ Topic A │  │ Topic B │  │    Topic C   │  │
│  │  Queue  │  │ Queue 1 │  │  Partition 0 │  │
│  │         │  │ Queue 2 │  │  Partition 1 │  │
│  └─────────┘  └─────────┘  │  Partition 2 │  │
│                            └─────────────┘  │
└─────────────────────────────────────────────┘
```

---

## 二、消息通信模型

### 2.1 点对点模型 (Point-to-Point / Queue)

**特点**：
- 一条消息只能被**一个消费者**消费
- 消息消费后从队列中移除
- 多个消费者可实现负载均衡

```
Producer ──▶ [Queue] ──▶ Consumer 1 (处理消息1)
                │
                ├──Msg3
                ├──Msg2
                └──Msg1 ──▶ Consumer 2 (处理消息2)
```

**适用场景**：任务分发、订单处理、工作队列

### 2.2 发布/订阅模型 (Publish/Subscribe / Topic)

**特点**：
- 一条消息可以被**多个消费者**同时消费
- 消息不会从主题中移除（除非过期）
- 每个消费者收到消息的独立副本

```
               ┌───▶ Consumer 1 (短信通知)
Producer ──▶ Topic ──▶ Consumer 2 (邮件通知)
               └───▶ Consumer 3 (日志记录)
```

**适用场景**：事件广播、新闻推送、日志分发

### 2.3 两种模型对比

| 维度 | 点对点 (Queue) | 发布/订阅 (Topic) |
|------|---------------|-------------------|
| 消息消费 | 单消费者（独占式） | 多消费者（广播式） |
| 消息移除 | 消费后移除 | 独立保留 |
| 顺序性 | 队列内严格有序 | 分区内有序 |
| 扩展性 | 消费者负载均衡 | 订阅者独立扩展 |
| 典型实现 | ActiveMQ Queue、RabbitMQ Queue | Kafka Topic、RocketMQ Topic |
| 适用场景 | 任务分发 | 事件广播 |

### 2.4 两种协议标准

**AMQP (Advanced Message Queuing Protocol)**：
- 面向企业级的开放标准协议
- 核心组件：Exchange（交换机）→ Queue（队列）← Binding（绑定关系）
- 支持复杂消息路由
- 代表实现：RabbitMQ

**MQTT (Message Queuing Telemetry Transport)**：
- 轻量级、低功耗的发布-订阅协议
- QoS 三级服务质量（至多一次/至少一次/精确一次）
- 专为物联网设计
- 适用：IoT 设备通信、移动推送

---

## 三、主流 MQ 全面对比与选型

### 3.1 三大 MQ 简介

| 产品 | 开发语言 | 出身 | 特点标签 |
|------|----------|------|----------|
| **Kafka** | Scala + Java | LinkedIn → Apache | 高吞吐、大数据、流处理 |
| **RabbitMQ** | Erlang | Pivotal → VMware | 灵活路由、低延迟、多协议 |
| **RocketMQ** | Java | 阿里巴巴 → Apache | 事务消息、顺序消息、电商级可靠 |

### 3.2 性能对比

| 维度 | Kafka | RabbitMQ | RocketMQ |
|------|-------|----------|----------|
| 单机吞吐量 | **百万级 TPS** | 万级～十万级 TPS | 十万级 TPS |
| 延迟 | 毫秒级 | **微秒级**（最快） | 毫秒级 |
| 集群扩展性 | **极强**（分区无限扩展） | 一般（镜像队列性能开销大） | 强（DLedger 自动选主） |
| Topic 数量上限 | 64 个分区后负载明显增加 | 队列数量增加影响性能 | **单机支持 5 万队列** |

### 3.3 功能对比

| 功能 | Kafka | RabbitMQ | RocketMQ |
|------|-------|----------|----------|
| 事务消息 | 有限支持 | 支持 | ✅ **原生支持** |
| 顺序消息 | 分区内有序 | 有限支持 | ✅ **严格有序** |
| 延迟消息 | 需自行实现 | 通过插件 | ✅ **内置 18 个延迟级别** |
| 消息回溯 | ✅ 按 Offset | ❌ 不支持 | ✅ **按时间回溯** |
| 消息查询 | ❌ | ❌ | ✅ **支持消息查询** |
| 重试队列 | ❌ | ✅（手动/自动） | ✅ **内置重试 Topic** |
| 死信队列 | ❌ 需自建 | ✅ 内置 | ✅ **内置 DLQ** |
| Tag 过滤 | ❌ | 头部属性 | ✅ **内置 Tag 过滤** |
| 协议支持 | 自定义 | AMQP/MQTT/STOMP | gRPC/REST/Kafka 兼容 |

### 3.4 架构对比

| 维度 | Kafka | RabbitMQ | RocketMQ |
|------|-------|----------|----------|
| 存储模型 | **分区 (Partition)** 追加写 | **队列 (Queue)** + Exchange路由 | **CommitLog 统一写 + ConsumeQueue 索引** |
| 消息顺序 | 分区内有序 | 单消费者有序 | 队列级严格有序 |
| 副本机制 | ISR 多副本 | 镜像队列 | 主从同步 / DLedger |
| 协调服务 | ZK / KRaft (3.x+) | 内置 Mnesia | NameServer (无状态) |
| 消费模型 | Pull（拉模式） | Push/Pull | Pull（长轮询） |

### 3.5 Kafka vs RocketMQ 深度对决

| 维度 | Kafka | RocketMQ |
|------|-------|----------|
| **设计哲学** | 分布式日志系统，追求**高吞吐+大规模水平扩展** | 企业级消息系统，追求**业务可靠性+低延迟** |
| **存储核心** | Partition 各自顺序写 | CommitLog 统一顺序写 + ConsumeQueue 索引 |
| **订单场景** | 需要自己保证顺序，实现复杂 | **天然支持**，队列内严格有序 |
| **延迟消息** | 需自行实现 | **内置支持**，18 个延迟级别 |
| **分布式事务** | 实现复杂，不推荐 | **原生支持**事务消息 |
| **业务友好** | 低（无 Tag、重试、DLQ） | **高**（Tag、重试、DLQ 一应俱全） |

**总结一句话**：
> Kafka 是大数据系统的"超高速消息日志"；RocketMQ 是企业级业务系统的"可靠消息中间件"。

### 3.6 选型决策树

```
你的主要需求是什么？
│
├──▶ 日志收集、埋点、大数据流处理
│    └──▶ 选 Kafka（配合 Flink/Spark/ELK）
│
├──▶ 订单/交易/支付等核心业务
│    ├──▶ 需要分布式事务 → RocketMQ
│    ├──▶ 需要延迟消息 → RocketMQ
│    ├──▶ 需要严格顺序 → RocketMQ
│    └──▶ 需要低延迟+复杂路由 → RabbitMQ
│
├──▶ IoT 设备、移动推送
│    └──▶ RabbitMQ（支持 MQTT）
│
├──▶ 数据管道、CDC、流式管道
│    └──▶ Kafka（Kafka Connect 生态）
│
└──▶ 传统企业应用、JMS 兼容
     └──▶ ActiveMQ（不推荐新项目）
```

---

## 四、Apache Kafka 详解

### 4.1 Kafka 架构

```
┌────────────────────────────────────────────────────────┐
│                    Kafka Cluster                        │
│                                                        │
│   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐│
│   │   Broker 1   │   │   Broker 2   │   │   Broker 3   ││
│   │              │   │              │   │              ││
│   │ Part 0 [L]   │   │ Part 0 [F]   │   │ Part 1 [L]   ││
│   │ Part 1 [F]   │   │ Part 2 [F]   │   │ Part 2 [L]   ││
│   │              │   │ Part 1 [F]   │   │ Part 0 [F]   ││
│   └──────────────┘   └──────────────┘   └──────────────┘│
│                                                        │
│    L = Leader, F = Follower                             │
└────────────────────────────────────────────────────────┘
         ▲                                      │
         │ produce                              │ consume
         │                                      ▼
   ┌──────────┐                        ┌─────────────┐
   │ Producer │                        │ Consumer    │
   │          │                        │ Group       │
   └──────────┘                        └─────────────┘
```

### 4.2 核心概念

| 概念 | 说明 |
|------|------|
| **Topic** | 消息的逻辑分类，类似数据库的表 |
| **Partition** | Topic 的物理分区，每个分区是一个有序的不可变日志 |
| **Broker** | Kafka 服务节点 |
| **Producer** | 消息生产者，决定消息写入哪个 Partition |
| **Consumer** | 消息消费者，属于某个 Consumer Group |
| **Consumer Group** | 消费者组，组内消费者分摊消费，组间广播消费 |
| **Offset** | 消息在分区中的唯一位置标识 |
| **ISR** | In-Sync Replicas，与 Leader 保持同步的副本集合 |
| **Leader/Follower** | 每个分区有一个 Leader 处理读写，Follower 同步备份 |

### 4.3 分区机制

```
Topic: "orders"
│
├── Partition 0: [msg0] [msg1] [msg2] [msg3] ... → 顺序写磁盘，Offset递增
│
├── Partition 1: [msg0] [msg1] [msg2] ... 
│
└── Partition 2: [msg0] [msg1] [msg2] [msg3] [msg4] ...
```

**分区的好处**：
1. **水平扩展**：一个 Topic 可以通过分区分布在多台 Broker 上
2. **并行消费**：消费者组内的消费者可以并行消费不同分区
3. **顺序保证**：分区内消息严格有序

**消息路由到分区的策略**：
- 指定 Key → `hash(key) % partitionCount`
- 未指定 Key → 轮询 (round-robin)

**重要约束**：消费者组内的消费者数 ≤ 分区数（多余消费者空闲）

### 4.4 生产者关键配置

```properties
# 确认机制
acks=0        # 不等待确认（最快，可能丢消息）
acks=1        # 等待 Leader 确认���平衡）
acks=all      # 等待所有 ISR 确认（最可靠，最慢）

# 重试机制
retries=3
retry.backoff.ms=100

# 幂等性（防止重复发送）
enable.idempotence=true

# 批量发送
batch.size=16384
linger.ms=10    # 延迟发送，攒批次

# 压缩
compression.type=snappy
```

### 4.5 消费者关键配置

```properties
# 是否自动提交 offset
enable.auto.commit=false          # 推荐手动提交

# Offset 重置策略（无已提交 offset 时）
auto.offset.reset=earliest        # 从头开始
auto.offset.reset=latest          # 从最新开始

# 心跳间隔
heartbeat.interval.ms=3000
session.timeout.ms=30000

# 每次拉取最大数据量
max.poll.records=500
fetch.max.bytes=52428800
```

### 4.6 高可用设计

**副本机制**：
```
Partition 0:
  ┌─────────────────────────────────────────────┐
  │ Broker 1              │ Broker 2              │ Broker 3              │
  │ Leader (读写)          │ Follower (同步备份)    │ Follower (同步备份)    │
  └─────────────────────────────────────────────┘
  ISR = [Broker 1, Broker 2, Broker 3]  // 都同步正常
```

**Leader 故障 → 自动选举**：
1. Controller 节点检测到 Leader 宕机
2. 从 ISR 中选举一个新 Leader
3. 生产者和消费者自动切换到新 Leader

### 4.7 Kafka 代码示例

**Java 生产者**：
```java
Properties props = new Properties();
props.put("bootstrap.servers", "localhost:9092");
props.put("key.serializer", "org.apache.kafka.common.serialization.StringSerializer");
props.put("value.serializer", "org.apache.kafka.common.serialization.StringSerializer");
props.put("acks", "all");

Producer<String, String> producer = new KafkaProducer<>(props);
producer.send(new ProducerRecord<>("my-topic", "key1", "message value"));
producer.close();
```

**Java 消费者**：
```java
Properties props = new Properties();
props.put("bootstrap.servers", "localhost:9092");
props.put("key.deserializer", "org.apache.kafka.common.serialization.StringDeserializer");
props.put("value.deserializer", "org.apache.kafka.common.serialization.StringDeserializer");
props.put("group.id", "my-group");
props.put("enable.auto.commit", "false");

Consumer<String, String> consumer = new KafkaConsumer<>(props);
consumer.subscribe(Arrays.asList("my-topic"));

while (true) {
    ConsumerRecords<String, String> records = consumer.poll(Duration.ofMillis(100));
    for (ConsumerRecord<String, String> record : records) {
        // 处理消息
        System.out.printf("offset=%d, key=%s, value=%s%n",
            record.offset(), record.key(), record.value());
    }
    consumer.commitSync(); // 手动提交 offset
}
```

### 4.8 Kafka 适用场景

- ✅ 日志收集与分析（ELK 体系）
- ✅ 流式计算（Flink、Spark、Kafka Streams）
- ✅ 用户行为埋点采集
- ✅ 大规模事件流管道
- ✅ 数据库 CDC（Debezium + Kafka Connect）
- ⚠️ 不推荐用于强事务一致性业务

---

## 五、RabbitMQ 详解

### 5.1 RabbitMQ 架构

```
Producer ──▶ Exchange ──(binding key)──▶ Queue ──▶ Consumer
                │
                ├── routing key = "error" ──▶ Queue A
                ├── routing key = "info"  ──▶ Queue B
                └── routing key = "warn"  ──▶ Queue C
```

**核心三要素**：
- **Exchange（交换机）**：接收生产者的消息，根据路由规则分发到队列
- **Queue（队列）**：存储消息，消费者从队列获取消息
- **Binding（绑定）**：定义 Exchange 和 Queue 之间的路由关系

### 5.2 四种 Exchange 类型

| 类型 | 路由规则 | 类比 | 使用场景 |
|------|----------|------|----------|
| **Direct** | routing key **精确匹配** | 直接快递到指定地址 | 精确路由、单点通知 |
| **Fanout** | **广播**，忽略 routing key | 小区公告广播 | 订单成功后群发通知 |
| **Topic** | routing key **模式匹配**（`*` 单层 / `#` 多层） | 智能分发（按主题规则） | 复杂分类路由 |
| **Headers** | 根据 Header 属性匹配 | 不看收件人看包裹标签 | 复杂条件路由 |

### 5.3 Exchange 路由详解

**Direct Exchange**（精确匹配）：

```
                 ┌──▶ Queue A (routing key = "error")
Producer ──▶ [X]─┤
                 └──▶ Queue B (routing key = "info")
```

**Fanout Exchange**（广播）：

```
                 ┌──▶ Queue A
Producer ──▶ [X]─┼──▶ Queue B
                 └──▶ Queue C
```

**Topic Exchange**（模式匹配）：

```
                 ┌──▶ Queue A (binding = "order.*")     → 匹配 "order.create", "order.pay"
Producer ──▶ [X]─┤
                 └──▶ Queue B (binding = "order.#")     → 匹配全部 "order.xxx.yyy"
```

### 5.4 消息确认机制

**生产端确认**：

| 机制 | 说明 |
|------|------|
| Confirm 模式 | 生产者等待 Broker 确认消息已接收 |
| Return 回调 | 消息无法路由到队列时回调通知 |

```java
// 发布确认
channel.confirmSelect();
channel.basicPublish("exchange", "routingKey", null, message.getBytes());
if (channel.waitForConfirms()) {
    // 发送成功
}
```

**消费端确认 (ACK)**：

| 模式 | 说明 |
|------|------|
| 自动确认 (autoAck=true) | 消息发出即认为消费成功（可能丢消息） |
| 手动确认 (autoAck=false) | 消费者显式确认后删除消息（推荐） |

```java
// 手动确认模式
channel.basicQos(1); // 每次预取1条（公平分发）
channel.basicConsume("queue", false, (consumerTag, delivery) -> {
    String message = new String(delivery.getBody());
    try {
        processMessage(message);
        channel.basicAck(delivery.getEnvelope().getDeliveryTag(), false); // 确认
    } catch (Exception e) {
        channel.basicNack(delivery.getEnvelope().getDeliveryTag(), false, true); // 拒绝并重新入队
    }
}, consumerTag -> {});
```

### 5.5 高级特性

#### 5.5.1 死信队列 (DLX)

**死信的三种来源**：
1. 消息被消费者拒绝（basic.reject / basic.nack），且 `requeue=false`
2. 消息 TTL 到期
3. 队列满（达到最大长度）

```
正常队列 (设置了 TTL + DLX)
    │
    ├── Msg 正常消费
    │
    └── Msg 过期/被拒/队列满
           │
           └──▶ 死信交换机(DLX) ──▶ 死信队列 ──▶ 人工处理/定时重试
```

**配置死信队列**：
```java
// 声明死信交换机
@Bean
public DirectExchange deadLetterExchange() {
    return new DirectExchange("dlx.exchange");
}

// 声明死信队列
@Bean
public Queue deadLetterQueue() {
    return QueueBuilder.durable("dlx.queue").build();
}

// 声明正常队列并绑定死信
@Bean
public Queue normalQueue() {
    return QueueBuilder.durable("normal.queue")
        .deadLetterExchange("dlx.exchange")   // 死信交换机
        .deadLetterRoutingKey("dlx.key")       // 死信路由键
        .ttl(30000)                            // 消息 TTL 30秒
        .maxLength(10000)                      // 最大长度
        .build();
}
```

#### 5.5.2 延迟队列

**两种实现方式**：

**方式一：TTL + DLX 组合**：
```java
// 创建延迟交换机(插件方式)
@Bean
public CustomExchange delayExchange() {
    Map<String, Object> args = new HashMap<>();
    args.put("x-delayed-type", "direct");
    return new CustomExchange("delay.exchange", "x-delayed-message", true, false, args);
}

// 发送延迟消息
rabbitTemplate.convertAndSend("delay.exchange", "delay.key", message, msg -> {
    msg.getMessageProperties().setDelay(10000); // 延迟 10 秒
    return msg;
});
```

#### 5.5.3 惰性队列 (Lazy Queue)

消息直接写入磁盘，消费时才加载到内存：
```java
@Bean
public Queue lazyQueue() {
    return QueueBuilder.durable("lazy.queue")
        .withArgument("x-queue-mode", "lazy")
        .build();
}
```

**适用场景**：消息量大、消息堆积容忍度高（支持百万级消息存储）

### 5.6 RabbitMQ 集群方式

| 模式 | 说明 | 优缺点 |
|------|------|--------|
| **普通集群** | 共享元数据，队列只存于一个节点 | 简单，节点宕机数据丢失 |
| **镜像队列** | 队列数据复制到多个节点 | 高可用，性能开销大 |
| **仲裁队列** | 基于 Raft 协议，强一致性 | 可靠性最高，3.8+ 新增 |

### 5.7 RabbitMQ 适���场景

- ✅ 企业级应用（ERP、CRM）
- ✅ 低延迟实时消息（IM、在线游戏指令）
- ✅ 复杂路由场景
- ✅ 金融支付系统
- ✅ 微服务间异步通信
- ⚠️ 不适合超高吞吐场景

---

## 六、Apache RocketMQ 详解

### 6.1 RocketMQ 架构

```
┌─────────────────────────────────────────────────────────────────┐
│                     RocketMQ Cluster                            │
│                                                                 │
│   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│   │ NameServer 1 │  │ NameServer 2 │  │ NameServer 3 │         │
│   │  (路由中心)   │  │  (路由中心)   │  │  (路由中心)   │         │
│   └──────────────┘  └──────────────┘  └──────────────┘         │
│         ▲                  ▲                  ▲                 │
│   ┌─────┴──────────────────┴──────────────────┴─────┐          │
│   │                    Broker 集群                    │          │
│   │  ┌──────────────┐  ┌──────────────┐              │          │
│   │  │   Master 1   │  │   Master 2   │              │          │
│   │  │  CommitLog   │  │  CommitLog   │              │          │
│   │  │  ConsumeQueue│  │  ConsumeQueue│              │          │
│   │  └──────┬───────┘  └──────┬───────┘              │          │
│   │         │                  │                      │          │
│   │  ┌──────▼───────┐  ┌──────▼───────┐              │          │
│   │  │   Slave 1   │  │   Slave 2   │               │          │
│   │  └─────────────┘  └─────────────┘               │          │
│   └─────────────────────────────────────────────────┘          │
│         ▲                                      │                │
│    ┌──────────┐                          ┌──────────┐         │
│    │ Producer │                          │ Consumer │         │
│    └──────────┘                          └──────────┘         │
└─────────────────────────────────────────────────────────────────┘
```

### 6.2 核心组件

| 组件 | 说明 |
|------|------|
| **NameServer** | 无状态路由中心，提供服务发现（类似注册中心） |
| **Broker** | 消息存储节点，存储消息和消费进度 |
| **Producer** | 消息生产者，通过 NameServer 发现 Broker |
| **Consumer** | 消息消费者（支持集群消费和广播消费） |
| **CommitLog** | 统一消息存储文件（所有消息顺序写入） |
| **ConsumeQueue** | 消费队列索引（指向 CommitLog 的偏移量） |

### 6.3 存储模型

```
CommitLog (所有消息统一顺序写)
┌───────────────────────────────────────────────────┐
│ [Msg1 | Msg2 | Msg3 | Msg4 | Msg5 | Msg6 | ... ] │
└───────────────────────────────────────────────────┘
     ▲       ▲       ▲       ▲       ▲       ▲
     │       │       │       │       │       │
┌────┴──────┐│┌──────┴──────┐│┌──────┴──────┐│
│ConsumeQueue│││ConsumeQueue│││ConsumeQueue││
│ Topic A    │││ Topic B    │││ Topic A    ││
│ Queue 0    │││ Queue 0    │││ Queue 1    ││
│ offset➡Msg │││ offset➡Msg │││ offset➡Msg ││
└────────────┘│└────────────┘│└────────────┘│
```

**核心优势**：
- **CommitLog 单文件顺序写**：磁盘写入延迟最低
- **ConsumeQueue 索引**：消费定位 O(1)
- 利用操作系统的 mmap + PageCache，读性能极高

### 6.4 消息类型与使用

#### 6.4.1 普通消息

```java
// 同步发送
DefaultMQProducer producer = new DefaultMQProducer("producer-group");
producer.setNamesrvAddr("localhost:9876");
producer.start();

Message msg = new Message("TopicTest", "TagA", "Hello RocketMQ".getBytes());
SendResult result = producer.send(msg);
System.out.println("Send result: " + result);

producer.shutdown();
```

#### 6.4.2 顺序消息

**全局顺序** vs **分区顺序**：

```
// 分区顺序：相同 orderId 的消息发到同一个队列
Message msg = new Message("OrderTopic", "TagA", orderId, orderData.getBytes());
SendResult result = producer.send(msg, new MessageQueueSelector() {
    @Override
    public MessageQueue select(List<MessageQueue> mqs, Message msg, Object arg) {
        String orderId = (String) arg;
        int index = Math.abs(orderId.hashCode()) % mqs.size();
        return mqs.get(index);
    }
}, orderId);
```

```java
// 消费端：单线程顺序消费
consumer.registerMessageListener(new MessageListenerOrderly() {
    @Override
    public ConsumeOrderlyStatus consumeMessage(List<MessageExt> msgs, ConsumeOrderlyContext context) {
        for (MessageExt msg : msgs) {
            processMessage(msg);
        }
        return ConsumeOrderlyStatus.SUCCESS;
    }
});
```

#### 6.4.3 延迟消息

RocketMQ 内置 **18 个延迟级别**：
```
1s, 5s, 10s, 30s, 1m, 2m, 3m, 4m, 5m, 6m, 7m, 8m, 9m, 10m, 20m, 30m, 1h, 2h
```

```java
// 设置延迟级别 3（对应 10s）
Message msg = new Message("TopicTest", "TagA", data.getBytes());
msg.setDelayTimeLevel(3);
producer.send(msg);
```

**典型场景**：30 分钟未支付自动取消订单

#### 6.4.4 批量消息

```java
List<Message> messages = new ArrayList<>();
for (int i = 0; i < 100; i++) {
    messages.add(new Message("TopicTest", "TagA", ("Msg " + i).getBytes()));
}
producer.send(messages); // 注意：总大小不超过 1MB
```

#### 6.4.5 事务消息

详见第 12 章「事务消息与分布式事务」。

### 6.5 消费模式

| 模式 | 说明 | 适用场景 |
|------|------|----------|
| **集群消费 (CLUSTERING)** | 组内分摊消费（默认） | 负载均衡 |
| **广播消费 (BROADCASTING)** | 组内每个消费者都收到消息 | 通知所有节点 |

```java
consumer.setMessageModel(MessageModel.CLUSTERING);    // 集群消费
consumer.setMessageModel(MessageModel.BROADCASTING);  // 广播消费
```

### 6.6 重试机制与死信队列

```
消息消费失败
    │
    ├── 第1次失败 → 重试 (延迟 10s)
    │
    ├── 第2次失败 → 重试 (延迟 30s)
    │
    ├── ... (最多16次重试)
    │
    └── 16次全部失败 → 进入死信队列 (%DLQ%consumerGroup)
```

```java
consumer.registerMessageListener((MessageListenerConcurrently) (msgs, context) -> {
    for (MessageExt msg : msgs) {
        try {
            processMessage(msg);
            return ConsumeConcurrentlyStatus.CONSUME_SUCCESS;
        } catch (Exception e) {
            // 重试次数
            if (msg.getReconsumeTimes() >= 3) {
                // 记录日志，人工处理
                log.error("消息消费失败超过3次，msgId={}", msg.getMsgId());
                return ConsumeConcurrentlyStatus.CONSUME_SUCCESS; // 确认消费，避免死循环
            }
            return ConsumeConcurrentlyStatus.RECONSUME_LATER; // 稍后重试
        }
    }
    return ConsumeConcurrentlyStatus.CONSUME_SUCCESS;
});
```

### 6.7 RocketMQ 适用场景

- ✅ 电商交易系统（订单、支付、库存）
- ✅ 分布式事务（事务消息）
- ✅ 延迟消息（关单、补偿任务）
- ✅ 严格顺序消息
- ✅ 金融级高可靠场景
- ✅ 需要 Tag 过滤、消息查询、消息回溯
- ✅ 国内互联网公司在线业务首选

---

## 七、Spring Boot 集成实战

### 7.1 Spring Boot 集成 Kafka

**依赖**：
```xml
<dependency>
    <groupId>org.springframework.kafka</groupId>
    <artifactId>spring-kafka</artifactId>
</dependency>
```

**配置文件**：
```yaml
spring:
  kafka:
    bootstrap-servers: localhost:9092
    producer:
      key-serializer: org.apache.kafka.common.serialization.StringSerializer
      value-serializer: org.apache.kafka.common.serialization.StringSerializer
      acks: all
      retries: 3
    consumer:
      group-id: test-group
      key-deserializer: org.apache.kafka.common.serialization.StringDeserializer
      value-deserializer: org.apache.kafka.common.serialization.StringDeserializer
      enable-auto-commit: false
      auto-offset-reset: earliest
```

**生产者**：
```java
@Service
public class KafkaProducer {
    @Autowired
    private KafkaTemplate<String, String> kafkaTemplate;

    public void sendMessage(String topic, String key, String message) {
        kafkaTemplate.send(topic, key, message).addCallback(
            result -> log.info("发送成功: {}", result.getRecordMetadata()),
            ex -> log.error("发送失败: ", ex)
        );
    }
}
```

**消费者**：
```java
@Service
public class KafkaConsumer {
    @KafkaListener(topics = "order-topic", groupId = "order-consumer-group")
    public void onMessage(ConsumerRecord<String, String> record,
                          Acknowledgment ack) {
        try {
            String message = record.value();
            processOrder(message);
            ack.acknowledge(); // 手动确认
        } catch (Exception e) {
            log.error("消费失败, offset={}", record.offset(), e);
        }
    }
}
```

### 7.2 Spring Boot 集成 RabbitMQ

**依赖**：
```xml
<dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-amqp</artifactId>
</dependency>
```

**配置文件**：
```yaml
spring:
  rabbitmq:
    host: localhost
    port: 5672
    username: guest
    password: guest
    publisher-confirm-type: correlated   # 发布确认
    publisher-returns: true              # 路由失败回调
    listener:
      simple:
        acknowledge-mode: manual         # 手动确认
        prefetch: 1                      # 预取1条（公平分发）
```

**配置类（声明交换机、队列、绑定）**：
```java
@Configuration
public class RabbitMQConfig {

    // 声明交换机
    @Bean
    public DirectExchange orderExchange() {
        return new DirectExchange("order.exchange", true, false);
    }

    // 声明队列
    @Bean
    public Queue orderQueue() {
        return QueueBuilder.durable("order.queue")
            .deadLetterExchange("dlx.exchange")
            .deadLetterRoutingKey("dlx.key")
            .ttl(30000)
            .build();
    }

    // 绑定
    @Bean
    public Binding orderBinding() {
        return BindingBuilder.bind(orderQueue())
            .to(orderExchange())
            .with("order.create");
    }
}
```

**生产者**：
```java
@Service
public class RabbitMQProducer {
    @Autowired
    private RabbitTemplate rabbitTemplate;

    public void sendMessage(String exchange, String routingKey, String message) {
        rabbitTemplate.convertAndSend(exchange, routingKey, message);
    }
}
```

**消费者**：
```java
@Service
public class RabbitMQConsumer {
    @RabbitListener(queues = "order.queue")
    public void onMessage(String message, Channel channel, Message amqpMessage) throws IOException {
        try {
            processOrder(message);
            channel.basicAck(amqpMessage.getMessageProperties().getDeliveryTag(), false);
        } catch (Exception e) {
            channel.basicNack(amqpMessage.getMessageProperties().getDeliveryTag(), false, true);
        }
    }
}
```

### 7.3 Spring Boot 集成 RocketMQ

**依赖**：
```xml
<dependency>
    <groupId>org.apache.rocketmq</groupId>
    <artifactId>rocketmq-spring-boot-starter</artifactId>
    <version>2.3.0</version>
</dependency>
```

**配置文件**：
```yaml
rocketmq:
  name-server: localhost:9876
  producer:
    group: order-producer-group
    send-message-timeout: 3000
    retry-times-when-send-failed: 2
```

**生产者**：
```java
@Service
public class RocketMQProducer {
    @Autowired
    private RocketMQTemplate rocketMQTemplate;

    public void sendMessage(String topic, String message) {
        rocketMQTemplate.convertAndSend(topic, message);
    }

    // 顺序消息
    public void sendOrderlyMessage(String topic, String orderId, String message) {
        rocketMQTemplate.syncSendOrderly(topic + ":orderTag", message, orderId);
    }

    // 延迟消息
    public void sendDelayMessage(String topic, String message, int delayLevel) {
        rocketMQTemplate.syncSend(topic, MessageBuilder.withPayload(message).build(),
            3000, delayLevel);
    }

    // 事务消息
    public void sendTransactionMessage(String topic, String message) {
        rocketMQTemplate.sendMessageInTransaction(topic,
            MessageBuilder.withPayload(message).build(), null);
    }
}
```

**消费者**：
```java
@Service
@RocketMQMessageListener(
    topic = "order-topic",
    consumerGroup = "order-consumer-group",
    selectorExpression = "*"        // Tag 过滤
)
public class OrderConsumer implements RocketMQListener<String> {

    @Override
    public void onMessage(String message) {
        try {
            processOrder(message);
        } catch (Exception e) {
            log.error("消费失败，消息将自动重试", e);
            throw e; // 抛出异常触发重试
        }
    }
}

// 顺序消费
@Service
@RocketMQMessageListener(
    topic = "order-topic",
    consumerGroup = "order-consumer-group",
    consumeMode = ConsumeMode.ORDERLY
)
public class OrderConsumerOrderly implements RocketMQListener<MessageExt> {
    @Override
    public void onMessage(MessageExt message) {
        processOrder(new String(message.getBody()));
    }
}
```

---

## 八、消息可靠性保障

消息从生产到消费经历三个阶段，每一阶段都有丢失的风险：

```
生产者 ──1──▶ Broker ──2──▶ 消费者 ──3──▶ 业务处理
  ↑  发送丢失    ↑  存储丢失    ↑  消费丢失
```

### 8.1 生产阶段：确保消息发送到 Broker

**三种安全等级**（以 Kafka 为例）：

| 等级 | 配置 | 可靠性 | 性能 |
|------|------|--------|------|
| 不等待确认 | `acks=0` | 低（可能丢失） | 最高 |
| Leader 确认 | `acks=1` | 中（Leader 宕机可能丢失） | 高 |
| 全部确认 | `acks=all` | **高（推荐）** | 较低 |

```java
// Kafka: acks=all + 幂等性
props.put("acks", "all");
props.put("enable.idempotence", "true");
props.put("retries", Integer.MAX_VALUE);

// RabbitMQ: 发布确认 + Return 回调
rabbitTemplate.setConfirmCallback((correlationData, ack, cause) -> {
    if (!ack) {
        log.error("消息发送失败, cause={}", cause);
        // 重试或记录落库
    }
});

rabbitTemplate.setReturnsCallback(returned -> {
    log.error("消息路由失败: {}", returned.getMessage());
});
```

### 8.2 存储阶段：确保 Broker 不丢消息

| MQ | 机制 | 关键配置 |
|----|------|----------|
| Kafka | 多副本 + ISR | `acks=all`, `min.insync.replicas=2` |
| RabbitMQ | 持久化队列 + 持久化消息 | `durable=true`, `deliveryMode=2` |
| RocketMQ | 同步刷盘 + 同步复制 | `flushDiskType=SYNC_FLUSH`, `brokerRole=SYNC_MASTER` |

```properties
# Kafka Broker 配置
min.insync.replicas=2       # 最少同步副本数
default.replication.factor=3 # 默认副本数
```

```java
// RabbitMQ: 持久化队列 + 消息
@Bean
public Queue durableQueue() {
    return new Queue("durable.queue", true); // durable=true
}
// 发送时设置消息持久化
rabbitTemplate.convertAndSend(exchange, routingKey, message, msg -> {
    msg.getMessageProperties().setDeliveryMode(MessageDeliveryMode.PERSISTENT);
    return msg;
});
```

### 8.3 消费阶段：确保消息被成功处理

| 方案 | 说明 | 风险 |
|------|------|------|
| 自动确认 | 拿到消息即确认 | 处理失败，消息丢失 |
| **手动确认** | 处理成功后确认 | 必须正确实现 |
| 手动拒绝 | 处理失败拒绝消息 | 可能死循环 |

```java
// Kafka: 关闭自动提交，处理成功后手动提交
props.put("enable.auto.commit", "false");
consumer.commitSync(); // 同步提交
// 或
consumer.commitAsync(); // 异步提交（性能更好）
```

```java
// RabbitMQ: 手动ACK
channel.basicAck(deliveryTag, false);  // 确认
channel.basicNack(deliveryTag, false, true);   // 拒绝并重新入队
channel.basicNack(deliveryTag, false, false);  // 拒绝不入队（进死信）
```

### 8.4 可靠性保障全景图

```
┌──────────────────────────────────────────────────────────────┐
│                    端到端消息可靠性保障                         │
│                                                              │
│  1. 发送阶段          2. 存储阶段          3. 消费阶段        │
│  ┌──────────┐       ┌──────────┐        ┌──────────┐        │
│  │ 同步发送  │  ──▶  │ 消息持久化│  ──▶  │ 手动 ACK │        │
│  │ 发布确认  │       │ 多副本同步│        │ 幂等处理  │        │
│  │ 重试机制  │       │ 同步刷盘 │        │ 死信队列  │        │
│  │ 事务消息  │       │ 集群部署 │        │ 重试机制  │        │
│  └──────────┘       └──────────┘        └──────────┘        │
│        │                                     │               │
│        └────────── 补偿机制 ──────────────────┘               │
│              (消息落库 + 定时扫描重发)                         │
└──────────────────────────────────────────────────────────────┘
```

---

## 九、消息幂等性

### 9.1 为什么会产生重复消息

```
「至少一次」投递语义下，以下场景会导致重复：
1. 生产者重试：等待超时，消息实际已发送成功
2. 消费者重试：处理成功但 ACK 超时，Broker 重新投递
3. Rebalance：消费者重平衡时消息重复消费
4. 手动提交失败：offset 未成功提交
```

### 9.2 幂等性保障方案

**方案一：数据库唯一键**

```java
public void processOrder(OrderMessage msg) {
    // 利用数据库唯一索引防止重复插入
    try {
        orderMapper.insert(Order.builder()
            .orderId(msg.getOrderId())
            .status(msg.getStatus())
            .build());
    } catch (DuplicateKeyException e) {
        log.info("订单已处理，跳过: orderId={}", msg.getOrderId());
        return;
    }
    // 后续业务逻辑...
}
```

**方案二：Redis 去重**

```java
public void processOrder(OrderMessage msg) {
    String deduplicationKey = "mq:consumed:" + msg.getMsgId();
    // SET NX 原子操作，设置过期时间 24 小时
    Boolean success = redisTemplate.opsForValue()
        .setIfAbsent(deduplicationKey, "1", 24, TimeUnit.HOURS);

    if (Boolean.FALSE.equals(success)) {
        log.info("消息已处理，跳过: msgId={}", msg.getMsgId());
        return;
    }
    // 业务处理...
}
```

**方案三：业务状态机**

```java
public void processOrder(OrderMessage msg) {
    // 查询当前订单状态
    Order order = orderMapper.selectById(msg.getOrderId());

    // 状态机：只有「待支付」→「已支付」才处理
    if (order.getStatus() != OrderStatus.PENDING_PAY) {
        log.info("订单状态不符合，跳过: orderId={}, currentStatus={}",
            msg.getOrderId(), order.getStatus());
        return;
    }

    order.setStatus(OrderStatus.PAID);
    orderMapper.updateById(order);
}
```

### 9.3 幂等性最佳实践总结

| 方案 | 实现成本 | 可靠性 | 适用场景 |
|------|----------|--------|----------|
| 数据库唯一键 | 低 | 高 | 插入操作 |
| Redis 去重 | 中 | 中（过期后可能重复） | 高频消费 |
| 业务状态机 | 低 | 高 | 有明确状态流转 |
| MQ 原生去重 | 低 | 高 | RocketMQ 支持 |
| 数据库 + 消息表 | 中 | 最高 | 核心交易 |

---

## 十、消息顺序性

### 10.1 为什么需要顺序性

**典型场景**：订单状态变更
```
创建订单 → 支付成功 → 发货 → 完成
  ✅         ✅         ✅      ✅  （正确顺序）
  ❌         先收到"发货"，再收到"支付成功" — 业务异常！
```

### 10.2 全局顺序 vs 分区顺序

| 类型 | 难度 | 吞吐量 | 实现方式 |
|------|------|--------|----------|
| **全局顺序** | 低 | 低（只有一个分区/队列） | 单分区 |
| **分区顺序** | 中 | 高（多个分区并行） | 相同 ID → 同一分区 |

**分区顺序（推荐）**：

```
Topic: orders (3 个分区)
│
├── Partition 0: [Order_A:创建] [Order_A:支付] [Order_A:发货]  ← A 的所有消息
│
├── Partition 1: [Order_B:创建] [Order_B:支付]                   ← B 的所有消息
│
└── Partition 2: [Order_C:创建] [Order_C:支付] [Order_C:发货]   ← C 的所有消息
```

### 10.3 各 MQ 实现顺序消费

**Kafka**：
```java
// 生产端：相同 key 的消息自动路由到同一分区
producer.send(new ProducerRecord<>("orders", orderId, orderData));
// Kafka 根据 key 的 hash 决定分区

// 消费端：单线程处理同一个分区的消息（天然有序）
```

**RocketMQ**：
```java
// 生产端：指定消息队列选择器
producer.send(msg, (mqs, msg, arg) -> {
    String orderId = (String) arg;
    int index = Math.abs(orderId.hashCode()) % mqs.size();
    return mqs.get(index);
}, orderId);

// 消费端：顺序消费监听器
consumer.registerMessageListener((MessageListenerOrderly) (msgs, context) -> {
    for (MessageExt msg : msgs) {
        processMessage(msg);
    }
    return ConsumeOrderlyStatus.SUCCESS;
});
```

**RabbitMQ**：
```java
// 通过 routing key 保证同一订单的消息进入同一队列
rabbitTemplate.convertAndSend("order.exchange", "order." + orderId, message);
// 单个队列单消费者，天然有序
```

---

## 十一、消息积压处理

### 11.1 消息积压的原因

- 消费者处理速度 < 生产者发送速度
- 消费者实例数不足
- 消费逻辑复杂、耗时长
- 下游服务故障（如数据库慢查询）
- 消费者线程阻塞

### 11.2 紧急处理步骤

```
1. 紧急扩容（最快解决）
   增加消费者实例数（Kafka: ≤ 分区数）
   临时启用多线程消费

2. 临时方案
   新建一个临时 Topic，将积压消息转发过去
   临时 Topic 分区数设为原 Topic 的 10 倍
   部署 10 倍消费者快速消费临时 Topic

3. 降级处理
   跳过非核心逻辑（如日志记录）
   返回降级结果（兜底数据）

4. 源头限流
   限制生产者发送速率
```

### 11.3 各 MQ 的预防方案

**Kafka**：
```java
// 增加分区数（需预先规划）
// 消费者数 ≤ 分区数

// 优化 poll 策略
props.put("max.poll.records", "500");
props.put("fetch.min.bytes", "1048576"); // 攒批后再拉取
```

**RabbitMQ**：
```java
// 使用惰性队列：消息直接写磁盘
Queue lazyQueue = QueueBuilder.durable("lazy.queue")
    .withArgument("x-queue-mode", "lazy")
    .build();

// 设置队列最大长度限制
Queue limitedQueue = QueueBuilder.durable("limited.queue")
    .maxLength(100000)
    .overflow(QueueBuilder.Overflow.rejectPublishDlx) // 超出进入死信
    .build();
```

**RocketMQ**：
```java
// 增加消费线程数
consumer.setConsumeThreadMax(64);     // 默认 64
consumer.setConsumeThreadMin(20);     // 默认 20

// 批量消费
consumer.setPullBatchSize(32);        // 每次拉取数量
consumer.setConsumeMessageBatchMaxSize(10);  // 每次消费批大小
```

### 11.4 监控告警

```
关键指标：
- Kafka: consumer lag > 10000
- RabbitMQ: queue messages ready > 100000
- RocketMQ: 消费堆积量 > 阈值
```

```bash
# Kafka 查看消费延迟
kafka-consumer-groups.sh --bootstrap-server localhost:9092 \
    --group my-group --describe

# RocketMQ 查看堆积
mqadmin consumerProgress -g my-group
```

---

## 十二、事务消息与分布式事务

### 12.1 什么是事务消息

事务消息保证"本地事务"和"消息发送"的原子性：**本地事务提交 = 消息一定发送成功**。

### 12.2 RocketMQ 事务消息流程

```
RocketMQ 事务消息（两阶段提交）：

阶段一：发送半消息 (Half Message)
┌──────────┐  (1)发送半消息    ┌───────────┐
│ Producer │ ───────────────▶ │  Broker   │
│          │                  │ 半消息暂存  │
│          │ ◀─────────────── │ (不可消费) │
└──────────┘  (2)半消息确认    └───────────┘
     │
     │ (3)执行本地事务
     ▼
┌───────────┐
│  数据库    │  更新订单状态...
└───────────┘
     │
     │ (4)提交/回滚
     ▼
┌──────────┐  (5)二次确认      ┌───────────┐
│ Producer │ ───────────────▶ │  Broker   │
│          │ ── COMMIT        │ 消息可消费  │
│          │ ── ROLLBACK     │ 消息删除   │
└──────────┘                  └───────────┘
```

**事务消息回查**：如果生产者一直没发二次确认，Broker 定期回查：
```
Broker ──回查──▶ Producer ──检查本地事务状态──▶ COMMIT / ROLLBACK
```

### 12.3 代码实现

```java
@Service
@RocketMQTransactionListener
public class OrderTransactionListener implements RocketMQLocalTransactionListener {

    @Override
    public RocketMQLocalTransactionState executeLocalTransaction(Message msg, Object arg) {
        String orderId = (String) arg;
        try {
            // 执行本地事务（如创建订单）
            orderService.createOrder(orderId);
            return RocketMQLocalTransactionState.COMMIT;
        } catch (Exception e) {
            return RocketMQLocalTransactionState.ROLLBACK;
        }
    }

    @Override
    public RocketMQLocalTransactionState checkLocalTransaction(Message msg) {
        // Broker 回查：检查本地事务状态
        String orderId = new String((byte[]) ((Map) msg).get("orderId"));
        Order order = orderMapper.selectById(orderId);
        if (order != null) {
            return RocketMQLocalTransactionState.COMMIT;
        }
        return RocketMQLocalTransactionState.ROLLBACK;
    }
}

// 发送事务消息
@Autowired
private RocketMQTemplate rocketMQTemplate;

public void sendTransactionMsg(String orderId) {
    rocketMQTemplate.sendMessageInTransaction(
        "order-topic",
        MessageBuilder.withPayload("创建订单：" + orderId).build(),
        orderId  // 传入参数
    );
}
```

### 12.4 事务消息典型场景

**电商下单扣库存**：
```
下单服务:
  1. 发送半消息到 MQ（"扣库存"）
  2. 执行本地事务（插入订单记录）
  3. 本地事务成功 → COMMIT → 库存服务消费消息扣库存
  4. 本地事务失败 → ROLLBACK → 消息不投递，不扣库存
```

### 12.5 Kafka 事务消息

Kafka 也支持事务（从 0.11 开始），但更侧重于**流处理中的精确一次语义**：

```java
// Kafka 事务生产者
props.put("transactional.id", "my-transactional-id");
props.put("enable.idempotence", "true");

KafkaProducer<String, String> producer = new KafkaProducer<>(props);
producer.initTransactions();

try {
    producer.beginTransaction();
    producer.send(new ProducerRecord<>("topic1", "key", "value"));
    producer.send(new ProducerRecord<>("topic2", "key", "value"));
    producer.commitTransaction();
} catch (Exception e) {
    producer.abortTransaction();
}
```

> **注意**：Kafka 事务消息实现复杂，性能开销大，在企业业务场景中不如 RocketMQ 事务消息实用。

---

## 十三、死信队列与延迟队列

### 13.1 死信队列 (DLQ)

**什么是死信**：
消息因以下原因无法被正常消费时，进入死信队列：
1. 消息被消费者明确拒绝（Nack/Reject）且不重新入队
2. 消息 TTL 到期未被消费
3. 队列达到最大长度/容量
4. 消息重试次数超过上限

**死信队列的价值**：
- 隔离"问题消息"，避免阻塞正常消息处理
- 提供人工干预入口（查看死信内容、手动重试）
- 配合监控告警

**各 MQ 的死信配置**：

| MQ | DLQ 机制 |
|----|----------|
| RabbitMQ | 原生支持，通过 deadLetterExchange 配置 |
| RocketMQ | 内置死信 Topic (%DLQ%consumerGroup) |
| Kafka | 无内置 DLQ，需自行实现（另建 Topic） |

### 13.2 延迟队列

**典型场景**：
- 订单30分钟未支付自动取消
- 退款7天后自动确认
- 定时推送消息
- 延迟重试

**实现方式对比**：

| 方案 | 说明 | 精度 |
|------|------|------|
| RocketMQ 内置 | 18 个固定延迟级别 | 粗粒度 |
| RabbitMQ 插件 | rabbitmq_delayed_message_exchange | 毫秒级 |
| Kafka | 需使用定时器 + 重试 Topic 模拟 | 依赖外部 |
| Redis ZSet | 按执行时间戳排序 | 秒级 |

**RocketMQ 延迟消息**：
```java
// 设置延迟级别（比如 level 3 = 10s）
msg.setDelayTimeLevel(3);
// 18 个级别: 1s 5s 10s 30s 1m 2m 3m 4m 5m 6m 7m 8m 9m 10m 20m 30m 1h 2h
```

**RabbitMQ 延迟插件**：
```java
// 申明延迟交换机
Map<String, Object> args = new HashMap<>();
args.put("x-delayed-type", "direct");
CustomExchange exchange = new CustomExchange("delay.exchange", "x-delayed-message", true, false, args);

// 发送延迟消息
rabbitTemplate.convertAndSend("delay.exchange", "order.cancel", orderData, msg -> {
    msg.getMessageProperties().setDelay(30 * 60 * 1000); // 延迟 30 分钟
    return msg;
});
```

---

## 十四、运维监控与故障排查

### 14.1 关键监控指标

| 指标 | Kafka | RabbitMQ | RocketMQ |
|------|-------|----------|----------|
| 消息堆积 (Lag) | consumer lag | queue messages ready | 消费堆积量 |
| 吞吐量 | bytes in/out per sec | message rates | TPS |
| 磁盘使用 | log.dirs 使用率 | 消息持久化占用 | commitLog 使用率 |
| 连接数 | connections count | connections | connections |
| 副本状态 | UnderReplicatedPartitions | 镜像同步状态 | 主从同步延迟 |
| JVM | GC + Heap | GC + Heap | GC + Heap |

### 14.2 常用诊断命令

**Kafka**：
```bash
# 查看消费延迟
kafka-consumer-groups.sh --bootstrap-server localhost:9092 \
    --group my-group --describe

# 查看 Topic 详情
kafka-topics.sh --bootstrap-server localhost:9092 \
    --describe --topic my-topic

# 查看分区副本状态
kafka-topics.sh --bootstrap-server localhost:9092 \
    --describe --under-replicated-partitions

# 查看 Broker 日志
tail -f /var/log/kafka/server.log
```

**RabbitMQ**：
```bash
# 管理界面 (默认开启)
http://localhost:15672

# 命令行查看队列
rabbitmqctl list_queues name messages_ready messages_unacknowledged consumers

# 查看连接
rabbitmqctl list_connections

# 查看交换机绑定
rabbitmqctl list_bindings
```

**RocketMQ**：
```bash
# 查看集群状态
mqadmin clusterList -n localhost:9876

# 查看 Topic 列表
mqadmin topicList -n localhost:9876

# 查看消费进度
mqadmin consumerProgress -g my-group

# 查看堆积
mqadmin msgAccumulation -t my-topic
```

### 14.3 常见问题排查

**问题1：消息堆积**：
```bash
# 1. 定位哪个消费者组堆积
kafka-consumer-groups.sh --bootstrap-server localhost:9092 --list

# 2. 查看具体 lag
kafka-consumer-groups.sh --bootstrap-server localhost:9092 \
    --group my-group --describe

# 3. 排查消费逻辑（是否有慢调用、死锁）
# 4. 增肌消费者实例
# 5. 优化消费逻辑（批量处理、异步化）
```

**问题2：消息丢失**：
```
排查流程：
1. 生产端：检查 acks 配置、重试次数
2. Broker：检查副本数、ISR 状态、持久化配置
3. 消费端：检查是否自动提交 offset、是否有异常吞没
```

**问题3：消费者无法消费**：
```
常见原因：
- 消费者组 offset 被重置
- Topic 分区数变更后 rebalance 失败
- Session 超时（session.timeout.ms 过小）
- 消费者组被删除重建
```

---

## 十五、开发最佳实践与避坑指南

### 15.1 通用实践

| 实践 | 说明 |
|------|------|
| **消息体大小控制** | 单条消息控制在 1MB 以内（Kafka 默认 1MB） |
| **序列化选择** | 使用 JSON/Protobuf/Avro，避免 JDK 原生序列化 |
| **消息过期设置** | 设置合理的 TTL，避免无用消息堆积 |
| **消费端幂等** | 所有消费端必须实现幂等性 |
| **手动提交 ACK** | 关闭自动提交，处理成功后再提交 |
| **合理分区** | 分区数 = max(消费者数 × 2, 预期吞吐量 / 单分区吞吐量) |
| **避免消费阻塞** | 消费逻辑中不调用耗时外部接口 |

### 15.2 Kafka 避坑

| 坑 | 解决方案 |
|----|----------|
| 消费者数 > 分区数 | 多余消费者空闲，需提前规划分区数 |
| `auto.offset.reset=latest` | 新消费者组可能丢失历史消息 |
| 频繁 rebalance | 增大 `session.timeout.ms` 和 `max.poll.interval.ms` |
| 分区 hot spot | 优化 Key 分配策略，避免数据倾斜 |
| ZK 性能瓶颈 | 升级到 KRaft 模式（Kafka 3.x+） |

### 15.3 RabbitMQ 避坑

| 坑 | 解决方案 |
|----|----------|
| 队列数量过多 | 控制队列数量，避免元数据膨胀 |
| 镜像队列性能 | 消息量不大时用镜像，大吞吐用普通集群 |
| 消息堆积 → 内存溢出 | 使用惰性队列（写入磁盘） |
| 连接数爆炸 | 配置连接池 + Channel 池化复用 |
| 死信堆积 | 监控死信队列，定期清理或告警 |

### 15.4 RocketMQ 避坑

| 坑 | 解决方案 |
|----|----------|
| 队列数创建后不可更改 | 提前规划好 Topic 的队列数 |
| NameServer 全部宕机 | NameServer 无状态，可随时重启；客户端有本地缓存 |
| 事务消息回查超时 | 检查回查线程池是否满，事务状态查询是否超时 |
| 消息大小超限 | RocketMQ 默认 4MB，注意消息体大小 |
| 消费端重试死循环 | 设置最大重试次数，超限后进入死信 |

### 15.5 消息队列选型清单

- [ ] 确定业务吞吐量（QPS 级别）
- [ ] 评估可靠性要求（是否允许丢消息）
- [ ] 确认是否需要顺序消息
- [ ] 确认是否需要事务消息
- [ ] 确认是否需要延迟消息
- [ ] 评估团队技术栈和运维能力
- [ ] 确认是否需要 Tag 过滤、消息查询
- [ ] 确认是否需要与大数据生态（Flink/Spark）集成

### 15.6 架构设计原则

1. **不把 MQ 当成数据库**：MQ 是异步通信管道，不是永久存储
2. **幂等性设计先行**：所有消息消费者从一开始就考虑幂等
3. **消费速度 > 生产速度**：永远保证消费者能消化生产者速率
4. **消息落库兜底**：核心业务消息入 MQ 前先落数据库
5. **异步不阻塞**：Producer 发送使用异步回调，Consumer 不阻塞
6. **监控全覆盖**：Lag、吞吐、磁盘、连接数全部接入监控

---

## 附录：参考资料

### 官方文档

- Apache Kafka: https://kafka.apache.org/documentation/
- RabbitMQ: https://www.rabbitmq.com/docs
- Apache RocketMQ: https://rocketmq.apache.org/docs/

### 参考文章

1. MQ 消息队列核心知识点总结 - https://blog.csdn.net/2302_78439400/article/details/147758448
2. 消息队列基础 - https://zstar.blog.csdn.net/article/details/151751295
3. 消息队列模型全景图 - https://blog.csdn.net/qq_44378083/article/details/149231168
4. 分布式消息中间件基础 - https://juejin.cn/post/7507473264798515235
5. RocketMQ 与 Kafka 详细对比 - https://www.cnblogs.com/xfydaydayup/p/19316423
6. 四大消息队列对比与选型 - https://juejin.cn/post/7556814348354633764
7. Kafka vs RabbitMQ vs RocketMQ 全方位对比 - https://blog.csdn.net/2301_78967994/article/details/153468479
8. Spring Boot 集成三大消息框架 - https://juejin.cn/post/7476614823883882534
9. 消息队列面试核心 - https://juejin.cn/post/7509354376991342611
10. 消息中间件 RabbitMQ & Kafka - https://blog.csdn.net/weixin_74191696/article/details/145538973
11. 电商异步消息系统实践 - https://cloud.baidu.com/article/4732562
12. Kafka 架构深度解析 - https://www.hikunpeng.com/developer/blog/details/0243188298486339097
13. RabbitMQ 高级特性 - https://cloud.tencent.cn/developer/article/2555649
14. Spring Boot 整合三大 MQ 最佳实践 - https://blog.csdn.net/canjun_wen/article/details/156124931

---

> **文档说明**：本文档基于 Kafka 3.x、RabbitMQ 3.12+、RocketMQ 5.x 版本编写，参考了网络上的最新技术资料和最佳实践。文档中的代码示例以 Java + Spring Boot 为主，涵盖了从基础概念到生产落地的全部内容。选型时请结合团队实际业务需求、技术栈和运维能力综合判断。

---

*文档生成时间：2025 年 | 持续更新中*
