# Redis 技术文档大全

---

## 目录

- [一、Redis 概述与架构](#一redis-概述与架构)
- [二、核心数据类型与底层实现](#二核心数据类型与底层实现)
- [三、持久化机制](#三持久化机制)
- [四、事务与 Lua 脚本](#四事务与-lua-脚本)
- [五、Pipeline 管道与性能优化](#五pipeline-管道与性能优化)
- [六、主从复制](#六主从复制)
- [七、哨兵模式 (Sentinel)](#七哨兵模式-sentinel)
- [八、Redis Cluster 集群](#八redis-cluster-集群)
- [九、内存管理与淘汰策略](#九内存管理与淘汰策略)
- [十、缓存三大问题：穿透、击穿、雪崩](#十缓存三大问题穿透击穿雪崩)
- [十一、分布式锁（核心高级应用）](#十一分布式锁核心高级应用)
- [十二、发布订阅与 Stream 消息队列](#十二发布订阅与-stream-消息队列)
- [十三、Redis 7.x 新特性](#十三redis-7x-新特性)
- [十四、运维监控与故障排查](#十四运维监控与故障排查)
- [十五、开发最佳实践与规范](#十五开发最佳实践与规范)
- [附录：参考资料](#附录参考资料)

---

## 一、Redis 概述与架构

### 1.1 Redis 是什么

Redis (Remote Dictionary Server) 是一个开源的、基于内存的、键值对 (Key-Value) 数据库。它具备以下核心特征：

- **内存存储**：数据存储在内存中，读写速度极快（单机 QPS 可达 10 万+）
- **单线程模型**：核心命令处理采用单线程，避免锁竞争和上下文切换（6.0 后引入多线程 I/O，但命令执行仍为单线程）
- **丰富的数据结构**：支持 String、Hash、List、Set、Sorted Set、Stream 等多种类型
- **持久化能力**：支持 RDB 快照和 AOF 日志两种持久化方式
- **高可用与分布式**：支持主从复制、哨兵自动故障转移、Cluster 集群分片

### 1.2 单线程模型与事件循环

Redis 的核心处理逻辑基于 **Reactor 模式的事件循环 (Event Loop)**：

```
┌─────────────────────────────────────────┐
│              Redis 进程                  │
│                                         │
│  ┌─────────────┐    ┌────────────────┐  │
│  │  I/O 多路复用 │───▶│  事件分发器     │  │
│  │  (epoll/kqueue)│   │ (File Event   │  │
│  └─────────────┘    │   Dispatcher)  │  │
│                      └───────┬────────┘  │
│                              │           │
│                    ┌─────────▼─────────┐ │
│                    │ 命令执行器(单线程)  │ │
│                    │ - 命令解析         │ │
│                    │ - 数据操作         │ │
│                    │ - 返回结果         │ │
│                    └───────────────────┘ │
└─────────────────────────────────────────┘
```

**单线程为何快？**

1. 完全基于内存，数据操作在纳秒级
2. 无锁竞争，无上下文切换开销
3. I/O 多路复用 (epoll)，单线程处理大量连接
4. 简单高效的数据结构实现

> **Redis 6.0+ 多线程 I/O**：仅网络读写使用多线程，命令执行仍为单线程，兼顾吞吐量与线程安全。

### 1.3 Redis 线程模型演进

| 版本 | 模型 | 说明 |
|------|------|------|
| 4.x 及以前 | 单线程 | I/O 和命令执行全部单线程 |
| 6.0 | 多线程 I/O | 网络读写多线程，命令执行单线程 |
| 7.0 | 多线程 I/O 增强 | 优化多线程性能，引入 listpack 等 |

### 1.4 适用场景

| 场景 | 说明 |
|------|------|
| 缓存 | 最常见用途，降低数据库压力 |
| 分布式锁 | 利用 SETNX / Redisson 实现 |
| 排行榜 | Sorted Set 天然支持排序 |
| 消息队列 | List / Pub-Sub / Stream |
| 计数器 | INCR 原子操作 |
| 会话存储 | Session 共享（分布式 Session） |
| 限流 | 令牌桶 / 滑动窗口 |
| 地理位置 | GEO 数据类型 |

---

## 二、核心数据类型与底层实现

### 2.1 String（字符串）

**基本操作**：
```bash
SET key value [EX seconds] [PX milliseconds] [NX|XX]
GET key
INCR key          # 原子递增
INCRBY key 10     # 指定步长递增
DECR key          # 原子递减
APPEND key "suffix"
STRLEN key
SETEX key 60 value  # 设置带过期时间的值
SETNX key value     # 仅当 key 不存在时设置（分布式锁基础）
MSET k1 v1 k2 v2   # 批量设置
MGET k1 k2         # 批量获取
```

**底层实现**：SDS (Simple Dynamic String)

SDS 是 Redis 对 C 字符串的增强实现，结构如下：

```c
struct sdshdr {
    int len;      // 已使用长度
    int free;     // 剩余空间
    char buf[];   // 字符数组
};
```

**SDS 优势**：
- **O(1) 获取长度**：直接读取 `len` 字段
- **空间预分配**：修改时预分配空间，减少内存重分配次数
- **惰性空间释放**：缩短时不立即释放，供后续使用
- **二进制安全**：可存储图片、序列化对象等二进制数据
- **缓冲区溢出保护**：拼接前检查空间

> **限制**：单个 String 值最大 512MB

**应用场景**：缓存对象 JSON、计数器、分布式锁、Token 存储

### 2.2 Hash（哈希）

**基本操作**：
```bash
HSET user:1001 name "Alice" age 25 email "alice@example.com"
HGET user:1001 name
HGETALL user:1001
HMSET user:1002 name "Bob" age 30       # 批量设置
HMGET user:1001 name age
HINCRBY user:1001 age 1                  # 字段值递增
HDEL user:1001 email
HEXISTS user:1001 name
HKEYS user:1001                          # 获取所有字段名
HVALS user:1001                          # 获取所有值
HLEN user:1001                           # 获取字段数量
```

**底层实现**：

| 条件 | 编码方式 | 说明 |
|------|----------|------|
| 元素数 ≤ 128 且值 ≤ 64 字节 | **listpack** (7.0+) / **ziplist** (7.0 前) | 连续内存，省内存 |
| 超过阈值 | **hashtable** | 哈希表，拉链法解决冲突 |

**渐进式 Rehash**：

当哈希表需要扩容/缩容时，Redis 采用渐进式 Rehash 策略：
1. 同时维护 `ht[0]`（旧表）和 `ht[1]`（新表）
2. 每次 CRUD 操作时，顺便迁移一小部分数据
3. 迁移完成后，释放 `ht[0]`，`ht[1]` 变为 `ht[0]`
4. 避免一次性 Rehash 导致服务停顿

**应用场景**：存储对象（用户信息、商品属性）、购物车

### 2.3 List（列表）

**基本操作**：
```bash
LPUSH messages "msg1" "msg2"     # 左侧插入
RPUSH messages "msg3"           # 右侧插入
LPOP messages                   # 左侧弹出
RPOP messages                   # 右侧弹出
LRANGE messages 0 -1            # 获取所有元素
LLEN messages                   # 获取长度
LINDEX messages 0               # 按索引获取
LSET messages 0 "updated"       # 按索引修改
LREM messages 2 "msg1"          # 删除指定元素
BLPOP messages 30               # 阻塞式左侧弹出（30秒超时）
BRPOP messages 30               # 阻塞式右侧弹出
```

**底层实现演进**：

| 版本 | 底层结构 | 说明 |
|------|----------|------|
| 3.2 之前 | ziplist / linkedlist | 小数据用 ziplist，大数据用双向链表 |
| 3.2+ | **quicklist** | ziplist 组成的双向链表，兼顾内存与性能 |
| 7.0+ | quicklist + **listpack** | listpack 替代 ziplist，消除连锁更新 |

**quicklist 结构**：
```
┌──────────┐    ┌──────────┐    ┌──────────┐
│ listpack │◀──▶│ listpack │◀──▶│ listpack │
│ [e1,e2]  │    │ [e3,e4]  │    │ [e5,e6]  │
└──────────┘    └──────────┘    └──────────┘
```

**应用场景**：消息队列、最新 N 条记录、文章列表

### 2.4 Set（集合）

**基本操作**：
```bash
SADD tags "redis" "database" "nosql"
SMEMBERS tags                  # 获取所有成员
SISMEMBER tags "redis"        # 判断是否成员
SCARD tags                     # 获取元素数量
SREM tags "nosql"              # 删除元素
SPOP tags                      # 随机弹出
SRANDMEMBER tags 2             # 随机获取2个元素

# 集合运算
SINTER set1 set2              # 交集
SUNION set1 set2              # 并集
SDIFF set1 set2               # 差集
SINTERSTORE result set1 set2  # 交集存入 result
```

**底层实现**：

| 条件 | 编码方式 |
|------|----------|
| 元素全为整数且数量 ≤ 512 | **intset**（整数集合，有序数组，二分查找 O(log N)） |
| 否则 | **hashtable** |

**应用场景**：标签系统、共同好友、抽奖、去重

### 2.5 Sorted Set（有序集合 / ZSet）

**基本操作**：
```bash
ZADD leaderboard 100 "Alice" 200 "Bob" 150 "Charlie"
ZRANGE leaderboard 0 -1 WITHSCORES              # 升序获取
ZREVRANGE leaderboard 0 2 WITHSCORES            # 降序获取前3名
ZRANGEBYSCORE leaderboard 100 200               # 按分数范围获取
ZRANK leaderboard "Alice"                       # 获取排名（升序）
ZREVRANK leaderboard "Alice"                   # 获取排名（降序）
ZSCORE leaderboard "Alice"                      # 获取分数
ZINCRBY leaderboard 50 "Alice"                  # 增加分数
ZREMRANGEBYRANK leaderboard 0 2                 # 按排名范围删除
ZCOUNT leaderboard 100 200                      # 按分数范围计数
```

**底层实现**：**跳表 (Skip List) + 哈希表 (dict)**

这是 Redis 中最复杂的数据结构，采用双数据结构协同工作：

```
Skip List (按分数排序，支持范围操作)
     │
     ├── Level 3: [header] ───────────────────────▶ [100] ─────────────▶ [200] ──▶ nil
     ├── Level 2: [header] ─────────▶ [150] ──────▶ [100] ─────────▶ [200] ──▶ nil
     └── Level 1: [header] ▶ [100] ▶ [150] ▶ [100] ▶ [200] ▶ nil
                                    │
Dict (member ──▶ score, O(1) 查找)
     └── "Alice" ──▶ 100, "Bob" ──▶ 200, "Charlie" ──▶ 150
```

- **dict**：存储 member → score 的映射，O(1) 查找分数
- **skiplist**：按 score 排序存储，支持范围查询（ZRANGEBYSCORE）和排名查询（ZRANK）
- 两结构通过指针共享相同数据，不浪费内存

**为何用跳表而非红黑树？**
1. 实现比平衡树简单
2. 范围查询更高效（直接遍历链表）
3. 并发优化更友好
4. 内存占用可通过参数控制层级

**应用场景**：排行榜、延迟队列（按时间戳作为 score）、带权重的消息队列

### 2.6 其他数据类型

| 类型 | 版本 | 说明 | 典型场景 |
|------|------|------|----------|
| **Stream** | 5.0+ | 消息队列，支持消费者组和消息回溯 | 事件流、消息队列 |
| **GEO** | 3.2+ | 地理位置信息（基于 ZSet） | 附近的人、距离计算 |
| **HyperLogLog** | 2.8.9+ | 基数估算（固定 12KB 内存） | UV 统计 |
| **Bitmap** | 2.2+ | 位操作 | 签到打卡、布隆过滤器 |
| **Bitfield** | 3.2+ | 多位位域操作 | 计数器 |

### 2.7 数据类型选择决策表

| 需求 | 推荐类型 | 示例 |
|------|----------|------|
| 缓存对象 | Hash | `HSET user:1 name "x" age 20` |
| 计数器 | String | `INCR page:views` |
| 排行榜 | ZSet | `ZADD rank 100 "user1"` |
| 消息队列 | List / Stream | `LPUSH msg "data"` |
| 去重 / 标签 | Set | `SADD tags "java"` |
| 签到 | Bitmap | `SETBIT sign:1:202501 5 1` |
| UV 统计 | HyperLogLog | `PFADD uv "user1"` |

---

## 三、持久化机制

Redis 提供两种持久化方式，生产环境建议**同时启用**。

### 3.1 RDB (Redis Database) 快照

**原理**：在指定时间间隔内，将内存数据集的快照写入磁盘。

```bash
# redis.conf
save 900 1     # 900秒内至少1次修改 → 触发快照
save 300 10    # 300秒内至少10次修改 → 触发快照
save 60 10000  # 60秒内至少10000次修改 → 触发快照

# 手动触发
BGSAVE          # 后台异步保存
SAVE            # 同步保存（阻塞，生产环境慎用）
```

**RDB 优点**：
- 二进制文件体积小，适合备份和灾难恢复
- 恢复速度快（直接加载二进制数据）
- 对 Redis 性能影响小（fork 子进程异步执行）

**RDB 缺点**：
- 可能丢失最后一次快照后的所有数据
- fork 子进程时，大数据集可能导致短暂服务暂停

### 3.2 AOF (Append Only File) 日志

**原理**：记录所有写操作命令，重启时重放命令恢复数据。

```bash
# redis.conf
appendonly yes                    # 开启 AOF
appendfilename "appendonly.aof"   # 文件名
appendfsync everysec               # 写入策略

# 三种写入策略
# always    - 每次写操作都同步到磁盘（最安全，性能最差）
# everysec  - 每秒同步一次（推荐，最多丢1秒数据）
# no        - 由操作系统决定何时同步（性能最好，安全性最低）
```

**AOF 重写 (Rewrite)**：

AOF 文件会不断增大，Redis 通过 BGREWRITEAOF 命令重写压缩：

```bash
# 手动触发
BGREWRITEAOF

# 自动触发
auto-aof-rewrite-percentage 100  # 文件大小比上次重写后增长100%时触发
auto-aof-rewrite-min-size 64mb   # AOF文件最小64MB才触发重写
```

**AOF 优点**：
- 数据安全性高，最多丢失 1 秒数据（everysec）
- 日志格式可读，可手动修复
- 支持重写压缩

**AOF 缺点**：
- 文件体积比 RDB 大
- 恢复速度比 RDB 慢（需重放命令）
- 写入性能略低于 RDB

### 3.3 RDB vs AOF 对比

| 对比项 | RDB | AOF |
|--------|-----|-----|
| 数据安全 | 可能丢失最后一次快照后的数据 | 最多丢失1秒（everysec） |
| 文件体积 | 小（二进制压缩） | 大（文本命令） |
| 恢复速度 | 快 | 慢 |
| 性能影响 | 小（fork 子进程） | 略大（每次写操作记录） |
| 可读性 | 不可读 | 可读（文本格式） |
| 适用场景 | 备份、灾难恢复 | 数据安全要求高 |

### 3.4 Redis 7.0 AOF 重要改进

Redis 7.0 对 AOF 进行了重大改进，采用 **Multi-Part AOF** 机制：

- 将 AOF 拆分为 **base 文件**（RDB 或 AOF 格式）+ **增量文件**（incr）
- 避免重写时阻塞
- 更高效的恢复机制

### 3.5 生产环境推荐配置

```bash
# 同时启用 RDB 和 AOF
save 900 1
save 300 10
save 60 10000

appendonly yes
appendfsync everysec
auto-aof-rewrite-percentage 100
auto-aof-rewrite-min-size 64mb

# 数据目录
dir /data/redis

# 内存上限
maxmemory 4gb
maxmemory-policy allkeys-lru
```

---

## 四、事务与 Lua 脚本

### 4.1 Redis 事务 (MULTI / EXEC)

Redis 事务是一组命令的集合，具有以下特点：

- **顺序执行**：事务中的命令按顺序执行
- **不被中断**：事务执行期间不会被其他客户端命令打断
- **不支持回滚**：如果某条命令出错，后续命令仍会执行（与关系型数据库不同）

```bash
# 基本事务
MULTI                # 开启事务
SET key1 "value1"
INCR counter
SET key2 "value2"
EXEC                 # 执行事务，返回所有命令的结果

# DISCARD            # 取消事务，所有命令不执行
```

**WATCH 乐观锁**：

```bash
WATCH stock:100      # 监视 key
MULTI
DECR stock:100
EXEC                 # 如果 stock:100 在 WATCH 后被修改，事务自动失败，返回 nil
```

> **注意**：WATCH 是一种乐观锁机制，如果被监视的 key 在 EXEC 前被修改，整个事务将失败。

### 4.2 Redis 事务的局限性

1. **不支持回滚**：命令执行出错不会回滚已执行的命令
2. **不支持条件分支**：没有 if/else 逻辑
3. **集群限制**：事务中的 key 必须在同一个哈希槽中
4. **不保证隔离性**：没有隔离级别概念

> 如果需要复杂的原子操作和条件逻辑，请使用 **Lua 脚本**。

### 4.3 Lua 脚本

Lua 脚本在 Redis 中以**原子方式**执行，不会被其他命令打断，是替代事务的最佳方案。

**基本语法**：
```lua
-- KEYS[1], KEYS[2]... 是传入的键名
-- ARGV[1], ARGV[2]... 是传入的参数

-- 示例：原子递减库存
local stock = tonumber(redis.call('GET', KEYS[1]))
if stock and stock > 0 then
    redis.call('DECR', KEYS[1])
    return 1  -- 成功
else
    return 0  -- 库存不足
end
```

**执行 Lua 脚本**：
```bash
# EVAL "脚本内容" key数量 key1 key2... arg1 arg2...
EVAL "return redis.call('SET', KEYS[1], ARGV[1])" 1 mykey "hello"

# 更复杂的示例：秒杀扣库存
EVAL "
local stock = tonumber(redis.call('GET', KEYS[1]))
if stock and stock > 0 then
    redis.call('DECR', KEYS[1])
    redis.call('RPUSH', KEYS[2], ARGV[1])
    return 1
end
return 0
" 2 stock:100 orders "user:1001"
```

**EVALSHA（缓存脚本）**：

```bash
# 先加载脚本，获取 SHA1 校验和
SCRIPT LOAD "return redis.call('SET', KEYS[1], ARGV[1])"
# 返回: "e0e1f9fabfc9d4800c877a703b823ac0578ff8d3"

# 后续使用 EVALSHA 执行，减少网络传输
EVALSHA "e0e1f9fabfc9d4800c877a703b823ac0578ff8d3" 1 mykey "hello"
```

**Lua 脚本的优势**：
- **原子性**：整个脚本作为一个整体执行，不会被中断
- **减少网络往返**：多条命令一次发送
- **复用性**：EVALSHA 缓存脚本，减少网络传输
- **复杂逻辑**：支持条件判断、循环等编程逻辑

**Lua 脚本注意事项**：
- 脚本不要太复杂，避免长时间阻塞 Redis
- 避免在脚本中使用 `KEYS *` 等阻塞命令
- 脚本应当快速执行完毕（毫秒级）
- 集群模式下，脚本中的 key 必须在同一个槽

### 4.4 事务 vs Lua vs Pipeline

| 特性 | 事务 (MULTI/EXEC) | Lua 脚本 | Pipeline |
|------|-------------------|----------|----------|
| 原子性 | 部分（不支持回滚） | 完全原子 | 无 |
| 条件逻辑 | 不支持 | 支持 | 不支持 |
| 网络往返 | 多次 | 1次 | 1次 |
| 复杂度 | 低 | 中 | 低 |
| 适用场景 | 简单批量操作 | 复杂原子操作 | 批量读写优化 |

---

## 五、Pipeline 管道与性能优化

### 5.1 Pipeline 原理

Pipeline 通过**批量发送命令、批量接收结果**，减少网络往返时间 (RTT)：

```
无 Pipeline (3次 RTT):
Client ──▶ SET k1 v1 ──▶ Server
Client ◀── OK ────────── Server
Client ──▶ SET k2 v2 ──▶ Server
Client ◀── OK ────────── Server
Client ──▶ SET k3 v3 ──▶ Server
Client ◀── OK ────────── Server

有 Pipeline (1次 RTT):
Client ──▶ SET k1 v1, SET k2 v2, SET k3 v3 ──▶ Server
Client ◀── OK, OK, OK ────────────────────────── Server
```

### 5.2 Pipeline 使用示例

**Java (Jedis)**：
```java
Jedis jedis = new Jedis("localhost", 6379);
Pipeline pipe = jedis.pipelined();
for (int i = 0; i < 1000; i++) {
    pipe.set("key:" + i, "value:" + i);
}
pipe.sync(); // 执行所有命令
```

**Python (redis-py)**：
```python
import redis
r = redis.Redis(host='localhost', port=6379)

pipe = r.pipeline()
for i in range(1000):
    pipe.set(f'key:{i}', f'value:{i}')
pipe.execute()
```

### 5.3 Pipeline 最佳实践

1. **批量大小控制**：每批 100-1000 条命令，总大小不超过 1MB
2. **不保证原子性**：单个命令失败不影响其他命令，需要手动处理错误
3. **集群限制**：Redis Cluster 中，同一 Pipeline 中的 key 必须在同一个哈希槽，否则报 CROSSSLOT 错误。使用 hash tag `{tag}` 确保 key 在同一槽：
   ```java
   pipeline.hset("{user:1001}:cart", "goods:2001", "1");
   pipeline.hset("{user:1001}:profile", "nickname", "Alice");
   pipeline.sync();
   ```
4. **何时不用 Pipeline**：2-3 条命令时，Pipeline 开销可能大于收益。命令数 ≥ 50 且网络延迟明显时使用

### 5.4 性能对比

| 操作方式 | 1000 条 SET 耗时 |
|----------|-----------------|
| 逐条执行 | ~1000ms (1000次 RTT) |
| Pipeline | ~50ms (1次 RTT) |
| Lua 脚本 | ~30ms (1次 RTT + 原子执行) |

---

## 六、主从复制

### 6.1 主从复制架构

```
        ┌──────────┐
        │  Master  │ (读写)
        └────┬─────┘
             │ 异步复制
    ┌────────┼────────┐
    ▼        ▼        ▼
┌───────┐ ┌───────┐ ┌───────┐
│Slave 1│ │Slave 2│ │Slave 3│  (只读)
└───────┘ └───────┘ └───────┘
```

**核心价值**：
- 读写分离：Master 写，Slave 读
- 数据冗余：提高数据安全性
- 读扩展：多个 Slave 分担读压力

### 6.2 复制流程

**全量同步**（首次连接或断线过久）：
1. 从节点发送 `PSYNC` 命令请求同步
2. 主节点执行 `BGSAVE` 生成 RDB 文件
3. 期间主节点的写命令记录到**复制缓冲区**
4. 主节点发送 RDB 文件给从节点
5. 从节点加载 RDB 文件，清空原有数据
6. 主节点发送缓冲区中的写命令
7. 从节点执行命令，完成同步

**增量同步**（断线后短时间内重连）：
1. 从节点维护 `replication offset`（复制偏移量）
2. 主节点维护 `replication backlog`（复制积压缓冲区）
3. 从节点重连时携带 offset
4. 主节点从 backlog 中找到对应位置，发送增量数据

### 6.3 配置主从复制

**从节点配置 (redis.conf)**：
```bash
# Redis 5.0+ 使用 replicaof（推荐）
replicaof 192.168.1.100 6379

# 从节点只读（推荐开启）
replica-read-only yes

# 主从认证密码（需与主节点 requirepass 一致）
masterauth "your_secure_password"

# 从节点优先级（用于哨兵选举，数字越大优先级越高）
replica-priority 100
```

**运行时动态配置**：
```bash
# 在从节点执行
REPLICAOF 192.168.1.100 6379

# 取消主从
REPLICAOF NO ONE
```

### 6.4 复制注意事项

- **异步复制**：主从同步是异步的，存在延迟
- **主从切换问题**：Master 故障需手动切换（或使用哨兵）
- **全量同步开销大**：大数据集全量同步会占用大量带宽和 CPU
- **复制积压缓冲区**：默认 1MB，高写入场景需调大 `repl-backlog-size`

---

## 七、哨兵模式 (Sentinel)

### 7.1 Sentinel 架构

```
┌──────────────────────────────────────────────────┐
│                Sentinel 集群 (3+ 节点)             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐         │
│  │Sentinel 1│  │Sentinel 2│  │Sentinel 3│         │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘         │
└───────┼─────────────┼─────────────┼───────────────┘
        │监控          │监控          │监控
        ▼              ▼              ▼
   ┌──────────┐  ┌──────────┐  ┌──────────┐
   │ Master   │  │ Slave 1  │  │ Slave 2  │
   │ (R/W)    │  │ (R)      │  │ (R)      │
   └──────────┘  └──────────┘  └──────────┘
```

### 7.2 Sentinel 核心功能

1. **监控**：持续监控 Master 和 Slave 是否存活
2. **通知**：通知运维或客户端 Redis 实例状态
3. **自动故障转移**：Master 宕机时自动选举新 Master
4. **配置提供者**：客户端连接 Sentinel 获取 Master 地址

### 7.3 故障转移流程

1. **主观下线 (SDOWN)**：单个 Sentinel 发现 Master 无响应
2. **客观下线 (ODOWN)**：超过 `quorum` 个 Sentinel 确认 Master 下线
3. **选举 Sentinel Leader**：Sentinel 之间通过 Raft 算法选出 Leader
4. **选择新 Master**：Leader 从 Slave 中选择优先级最高的作为新 Master
5. **执行切换**：
   - 将选中的 Slave 执行 `REPLICAOF NO ONE` 成为 Master
   - 通知其他 Slave 连接新 Master
   - 通知客户端新 Master 地址

### 7.4 Sentinel 配置

**sentinel.conf**：
```bash
# 监控的 Master 名称、IP、端口、quorum（最少多少个 Sentinel 同意才判定下线）
sentinel monitor mymaster 192.168.1.100 6379 2

# Master 无响应超过该时间(毫秒)判定为主观下线
sentinel down-after-milliseconds mymaster 5000

# 故障转移时，同时向新 Master 发起复制的 Slave 数量
sentinel parallel-syncs mymaster 1

# 故障转移超时时间(毫秒)
sentinel failover-timeout mymaster 60000

# Master 密码
sentinel auth-pass mymaster your_secure_password
```

### 7.5 启动 Sentinel

```bash
redis-sentinel /path/to/sentinel.conf
# 或
redis-server /path/to/sentinel.conf --sentinel
```

---

## 八、Redis Cluster 集群

### 8.1 Cluster 架构

Redis Cluster 通过**数据分片**实现水平扩展，采用 **16384 个哈希槽** 分布数据。

```
┌─────────────────────────────────────────────────────────┐
│                   Redis Cluster                         │
│                                                         │
│   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐    │
│   │  Master 1   │  │  Master 2   │  │  Master 3   │    │
│   │ 槽 0-5460   │  │ 槽 5461-10922│ │ 槽 10923-16383│   │
│   └──────┬──────┘  └──────┬──────┘  └──────┬──────┘    │
│          │                 │                 │            │
│   ┌──────▼──────┐  ┌──────▼──────┐  ┌──────▼──────┐    │
│   │  Replica 1  │  │  Replica 2  │  │  Replica 3  │    │
│   └─────────────┘  └─────────────┘  └─────────────┘    │
└─────────────────────────────────────────────────────────┘
```

### 8.2 数据分片原理

**哈希槽计算**：
```
slot = CRC16(key) mod 16384
```

- 每个 Master 节点负责一部分槽位
- 客户端可以访问任意节点
- 如果 key 不在当前节点的槽位范围内，返回 `MOVED` 重定向

**MOVED 重定向示例**：
```bash
# 连接 Master 1 (负责 0-5460)
127.0.0.1:6379> SET user:1 "Alice"
-> Redirected to slot [5474] located at 127.0.0.1:6380
OK
# 客户端自动连接 127.0.0.1:6380 并执行命令
# 同时缓存 slot 5474 → 127.0.0.1:6380 的映射关系
```

**Hash Tag**：
```bash
# 使用 {} 包裹的部分作为哈希计算依据
SET {user:1001}:profile "data"   # slot = CRC16("user:1001") % 16384
SET {user:1001}:cart "data"      # 同一 slot，支持事务和多键操作
```

### 8.3 集群配置

**redis.conf (每个节点)**：
```bash
port 6379
cluster-enabled yes                    # 启用集群模式
cluster-config-file nodes-6379.conf     # 集群元数据文件(自动生成)
cluster-node-timeout 15000              # 节点超时时间(毫秒)
cluster-require-full-coverage yes       # 槽位未全覆盖时是否停止服务

appendonly yes                          # 开启 AOF 持久化
daemonize yes
dir /data/redis/6379
logfile "/var/log/redis_6379.log"
requirepass yourpassword
masterauth yourpassword                 # 主从认证密码
```

**创建集群**：
```bash
# 创建 3 主 3 从集群
redis-cli --cluster create \
  192.168.1.10:6379 192.168.1.11:6379 192.168.1.12:6379 \
  192.168.1.13:6379 192.168.1.14:6379 192.168.1.15:6379 \
  --cluster-replicas 1 \
  -a yourpassword

# --cluster-replicas 1: 每个主节点配 1 个从节点
# 前面 N 个为主节点，后面 N*1 个为从节点
```

**集群管理命令**：
```bash
# 查看集群信息
redis-cli -c cluster info

# 查看节点列表
redis-cli -c cluster nodes

# 查看槽位分配
redis-cli -c cluster slots

# 添加节点
redis-cli --cluster add-node 192.168.1.16:6379 192.168.1.10:6379

# 重新分片（迁移槽位）
redis-cli --cluster reshard 192.168.1.10:6379

# 删除节点
redis-cli --cluster del-node 192.168.1.10:6379 <node-id>
```

### 8.4 故障转移

1. **节点检测**：节点间通过 Gossip 协议互相检测
2. **PFAIL（疑似下线）**：节点超时 `cluster-node-timeout` 未响应
3. **FAIL（确定下线）**：超过半数 Master 确认 PFAIL
4. **从节点选举**：
   - 下线 Master 的从节点发起选举
   - 获得超过半数 Master 投票后成为新 Master
   - 接管原 Master 的所有槽位
5. **集群更新**：其他节点更新槽位映射

### 8.5 Cluster 的限制

- **多键操作限制**：事务、Lua 脚本中的 key 必须在同一槽位
- **不支持 SELECT db**：只能使用 db 0
- **客户端复杂度高**：需处理 MOVED/ASK 重定向
- **最小集群**：至少 3 主 3 从

---

## 九、内存管理与淘汰策略

### 9.1 内存查看

```bash
INFO memory
```

关键指标：
```
used_memory: 850000000           # Redis 分配器分配的内存(字节)
used_memory_rss: 950000000       # 操作系统角度看 Redis 占用的内存
used_memory_peak: 1000000000     # 内存使用峰值
mem_fragmentation_ratio: 1.12    # 碎片率(rss/used)，>1.5 需优化
maxmemory: 4294967296            # 最大内存限制
```

### 9.2 过期策略

Redis 采用 **惰性删除 + 定期删除** 组合策略：

**惰性删除**：
- 访问 key 时检查是否过期
- 过期则删除，返回 nil
- 优点：对 CPU 友好，不额外消耗
- 缺点：过期 key 不被访问则一直占用内存

**定期删除**：
- 每隔一段时间随机抽取部分设置了 TTL 的 key 检查
- 默认每秒 10 次 (hz=10)
- 每次抽取 20 个 key，删除其中过期的
- 如果过期比例 > 25%，继续抽取

### 9.3 淘汰策略 (Eviction Policy)

当内存使用达到 `maxmemory` 限制时，Redis 根据 `maxmemory-policy` 淘汰数据：

| 策略 | 说明 | 适用场景 |
|------|------|----------|
| `noeviction` | 不淘汰，写入报错（默认） | 数据不能丢失 |
| `volatile-lru` | 从设过期的 key 中淘汰最近最少使用 | 缓存场景 |
| `volatile-lfu` | 从设过期的 key 中淘汰最不常用 (4.0+) | 缓存场景 |
| `volatile-random` | 从设过期的 key 中随机淘汰 | 缓存场景 |
| `volatile-ttl` | 从设过期的 key 中淘汰 TTL 最短的 | 缓存场景 |
| `allkeys-lru` | 从所有 key 中淘汰最近最少使用 | **纯缓存推荐** |
| `allkeys-lfu` | 从所有 key 中淘汰最不常用 (4.0+) | 纯缓存 |
| `allkeys-random` | 从所有 key 中随机淘汰 | 纯缓存 |

**LRU vs LFU**：
- **LRU (Least Recently Used)**：淘汰最长时间未使用的 key
- **LFU (Least Frequently Used)**：淘汰使用频率最低的 key（更精确的热点判断）

**推荐配置**：
```bash
# 纯缓存场景
maxmemory 4gb
maxmemory-policy allkeys-lru

# 混合场景（有持久化数据）
maxmemory 4gb
maxmemory-policy volatile-lru
```

### 9.4 内存优化技巧

1. **使用 Hash 替代多个 String**：
   - 存储 `user:1:name`, `user:1:age` → 改为 `HSET user:1 name "x" age 20`
   - 小 Hash 使用 listpack 编码，内存占用远低于多个 String

2. **控制 ziplist/listpack 阈值**：
   ```bash
   hash-max-listpack-entries 128    # Hash 元素数阈值
   hash-max-listpack-value 64      # Hash 值大小阈值
   list-max-listpack-size -2        # List 每个 listpack 大小
   set-max-listpack-entries 128    # Set 元素数阈值
   zset-max-listpack-entries 128   # ZSet 元素数阈值
   zset-max-listpack-value 64      # ZSet 值大小阈值
   ```

3. **使用 SCAN 替代 KEYS**：
   ```bash
   # 错误：阻塞 Redis
   KEYS user:*
   
   # 正确：游标式遍历
   SCAN 0 MATCH user:* COUNT 100
   ```

4. **控制大 Key**：
   - 单个 key 值不超过 1MB
   - List/Hash/Set 元素不超过 1 万
   - 使用 `redis-cli --bigkeys` 扫描大 key

5. **压缩存储对象**：
   - 存储前使用 gzip/snappy 压缩大对象

6. **内存碎片整理**：
   ```bash
   # 查看碎片率
   INFO memory  # mem_fragmentation_ratio > 1.5 需优化
   
   # 手动整理
   MEMORY PURGE
   
   # 自动整理 (4.0+)
   activedefrag yes
   active-defrag-ignore-bytes 100mb     # 碎片字节数达到此值才开始整理
   active-defrag-threshold-lower 10      # 碎片率达到 10% 开始整理
   active-defrag-cycle-min 1             # 整理占用 CPU 最小百分比
   active-defrag-cycle-max 25            # 整理占用 CPU 最大百分比
   ```

---

## 十、缓存三大问题：穿透、击穿、雪崩

### 10.1 缓存穿透 (Cache Penetration)

**定义**：查询一个**数据库中根本不存在**的数据，请求绕过缓存直达数据库。

```
用户请求 → 缓存未命中 → 数据库查询 → 数据库也不存在 → 每次请求都打到数据库
```

**场景**：恶意攻击（查询 ID=-1）、爬虫、程序 Bug。

**解决方案**：

**方案一：缓存空值**
```java
public User getUserById(String userId) {
    String cacheKey = "user:" + userId;
    User user = (User) redisTemplate.opsForValue().get(cacheKey);

    if (user != null) {
        // 缓存中存在（包括空值标记），直接返回
        return "NULL".equals(user) ? null : user;
    }

    // 缓存未命中，查询数据库
    user = userMapper.selectById(userId);
    if (user != null) {
        redisTemplate.opsForValue().set(cacheKey, user, 3600, TimeUnit.SECONDS);
    } else {
        // 数据库也不存在，缓存空值（短过期时间，如5分钟）
        redisTemplate.opsForValue().set(cacheKey, "NULL", 300, TimeUnit.SECONDS);
    }
    return user;
}
```

**方案二：布隆过滤器 (Bloom Filter)**
```java
@Service
public class UserService {

    @Autowired
    private RedissonClient redissonClient;

    private RBloomFilter<String> userBloomFilter;

    @PostConstruct
    public void initBloomFilter() {
        userBloomFilter = redissonClient.getBloomFilter("userBloomFilter");
        // 初始化：预期100万数据，误判率1%
        userBloomFilter.tryInit(1000000L, 0.01);
        // 预热：加载所有已存在的用户ID
        List<String> userIds = userMapper.selectAllUserIds();
        for (String id : userIds) {
            userBloomFilter.add(id);
        }
    }

    public User getUserByIdWithBF(String userId) {
        // 1. 布隆过滤器判断
        if (!userBloomFilter.contains(userId)) {
            return null; // 一定不存在，直接返回
        }
        // 2. 布隆过滤器判断可能存在，继续查缓存和数据库
        // ... 正常缓存查询逻辑
    }
}
```

**对比**：

| 方案 | 优点 | 缺点 |
|------|------|------|
| 缓存空值 | 实现简单 | 占用内存，短暂数据不一致 |
| 布隆过滤器 | 内存效率极高 | 有误判率，不支持删除，需预热 |

### 10.2 缓存击穿 (Cache Breakdown)

**定义**：某个**访问量极高的热点 Key** 在失效瞬间，大量并发请求穿透缓存直达数据库。

```
热点Key过期 → 10000个请求同时到达 → 全部穿透到数据库 → 数据库崩溃
```

**解决方案**：

**方案一：互斥锁 (Distributed Lock)**
```java
public Product getProductWithLock(String productId) {
    String cacheKey = "product:" + productId;
    Product product = (Product) redisTemplate.opsForValue().get(cacheKey);

    if (product == null) {
        // 缓存失效，获取分布式锁
        String lockKey = "lock:product:" + productId;
        RLock lock = redissonClient.getLock(lockKey);

        try {
            if (lock.tryLock(3, 10, TimeUnit.SECONDS)) {
                try {
                    // 双重检查：可能其他线程已重建缓存
                    product = (Product) redisTemplate.opsForValue().get(cacheKey);
                    if (product == null) {
                        product = productMapper.selectById(productId);
                        redisTemplate.opsForValue().set(cacheKey, product, 3600, TimeUnit.SECONDS);
                    }
                } finally {
                    lock.unlock();
                }
            } else {
                // 未获取锁，等待后重试
                Thread.sleep(100);
                return getProductWithLock(productId);
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }
    return product;
}
```

**方案二：逻辑过期**
```java
@Data
public class RedisData<T> {
    private T data;          // 实际数据
    private Long expireTime; // 逻辑过期时间戳(毫秒)
}

public Product getProductWithLogicalExpire(String productId) {
    String key = "product:" + productId;
    RedisData<Product> redisData = (RedisData<Product>) redisTemplate.opsForValue().get(key);

    if (redisData == null) {
        // 缓存不存在，直接查库并加载（预热）
        return loadProductToCache(productId);
    }

    // 检查是否逻辑过期
    if (redisData.getExpireTime() < System.currentTimeMillis()) {
        // 已过期，异步更新缓存，当前线程返回旧数据
        CACHE_REFRESH_EXECUTOR.submit(() -> {
            // 获取锁，确保只有一个线程更新
            RLock lock = redissonClient.getLock("lock:refresh:" + productId);
            if (lock.tryLock()) {
                try {
                    // 再次检查，防止重复更新
                    RedisData<Product> latest = (RedisData<Product>) redisTemplate.opsForValue().get(key);
                    if (latest.getExpireTime() < System.currentTimeMillis()) {
                        loadProductToCache(productId);
                    }
                } finally {
                    lock.unlock();
                }
            }
        });
    }
    return redisData.getData();
}
```

**对比**：

| 方案 | 一致性 | 可用性 | 复杂度 |
|------|--------|--------|--------|
| 互斥锁 | 强一致性 | 降低（需等待） | 中 |
| 逻辑过期 | 最终一致性 | 高（无等待） | 高 |

### 10.3 缓存雪崩 (Cache Avalanche)

**定义**：**大量缓存 Key 同时失效**，或 Redis 服务宕机，所有请求涌向数据库。

```
1000个Key同时过期 → 全部请求涌向数据库 → 数据库过载崩溃 → 系统瘫痪
```

**解决方案**：

**1. 差异化过期时间**：
```java
public void setProductWithRandomExpire(String productId, Product product) {
    String key = "product:" + productId;
    int baseTime = 3600;  // 基础过期时间：1小时
    int randomTime = new Random().nextInt(600); // 随机偏移：0-10分钟
    int expireTime = baseTime + randomTime;
    redisTemplate.opsForValue().set(key, product, expireTime, TimeUnit.SECONDS);
}
```

**2. 多级缓存架构**：
```
请求 → Caffeine (本地缓存, 1s TTL) → Redis (分布式缓存, 1h TTL) → 数据库
         ↓ 80% 请求在此拦截              ↓ 剩余请求
```

**3. 服务熔断与降级**：
```yaml
# Sentinel 配置
spring:
  cloud:
    sentinel:
      flow:
        - resource: queryProduct
          count: 5000       # QPS 限制
          grade: 1          # QPS 模式
      degrade:
        - resource: queryProduct
          count: 500        # 异常数阈值
          timeWindow: 10    # 熔断时间窗口(秒)
```

**4. 缓存预热**：
```java
@PostConstruct
public void preloadCache() {
    // 系统启动时预加载热点数据
    List<String> hotProductIds = productMapper.selectHotProductIds();
    for (String id : hotProductIds) {
        Product product = productMapper.selectById(id);
        setProductWithRandomExpire(id, product);
    }
}
```

### 10.4 三大问题总结

| 问题 | 本质 | 触发条件 | 核心解决方案 |
|------|------|----------|-------------|
| 穿透 | 查不存在数据 | 恶意攻击 / 无效参数 | 布隆过滤器 / 缓存空值 |
| 击穿 | 热点Key失效 | 热点Key过期 | 互斥锁 / 逻辑过期 |
| 雪崩 | 大量Key同时失效 | 相同过期时间 / Redis宕机 | 随机TTL / 多级缓存 / 熔断降级 |

---

## 十一、分布式锁（核心高级应用）

### 11.1 为什么需要分布式锁

在分布式系统中，多个服务实例可能同时操作共享资源，传统的单机锁（synchronized、ReentrantLock）无法跨 JVM 生效。

**典型场景**：
- 电商秒杀：防止库存超卖
- 账户扣款：防止余额扣超
- 定时任务：防止任务重复执行
- 限流：控制接口访问频率

### 11.2 分布式锁的必要条件

1. **互斥性**：任意时刻只有一个客户端持有锁
2. **可重入性**：同一线程可多次获取同一把锁
3. **锁超时**：持有锁的客户端崩溃时，锁能自动释放
4. **高可用**：锁服务自身不能成为单点故障
5. **非阻塞**：提供尝试获取锁的能力，不能无限等待

### 11.3 基础实现：SETNX

**最简单的 Redis 分布式锁**：

```bash
# SET key value NX EX seconds
# NX: 仅当 key 不存在时设置（互斥保证）
# EX: 设置过期时间（防止死锁）
SET lock:order:100 "client-uuid-xxx" NX EX 30
```

**Java 实现（基础版）**：
```java
public boolean tryLock(String lockKey, String requestId, int expireTime) {
    String result = jedis.set(lockKey, requestId, "NX", "EX", expireTime);
    return "OK".equals(result);
}
```

**释放锁（Lua 脚本保证原子性）**：
```lua
-- 释放锁：必须验证 value 是否匹配，防止误删别人的锁
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
else
    return 0
end
```

```java
public boolean releaseLock(String lockKey, String requestId) {
    String luaScript =
        "if redis.call('GET', KEYS[1]) == ARGV[1] then " +
        "   return redis.call('DEL', KEYS[1]) " +
        "else " +
        "   return 0 " +
        "end";
    Object result = jedis.eval(luaScript, Collections.singletonList(lockKey),
                                Collections.singletonList(requestId));
    return Long.valueOf(1).equals(result);
}
```

### 11.4 基础锁的问题

```
时间线：
T1: 客户端A获取锁，TTL=10s
T2: 客户端A执行业务逻辑，耗时15s（超过TTL）
T3: 10s后锁自动过期，客户端B获取锁成功
T4: 客户端A业务执行完毕，执行 DEL 释放锁
T5: ❌ 客户端A删除了客户端B的锁！
```

**问题清单**：
1. **锁过期但业务未完成** → 锁被其他客户端获取
2. **误删别人的锁** → 释放锁时未验证持有者
3. **不可重入** → 同一线程无法多次获取锁
4. **单点故障** → Redis 宕机导致锁丢失

### 11.5 进阶实现：Redisson 分布式锁

Redisson 是 Redis 官方推荐的 Java 客户端，提供了工业级的分布式锁实现。

**核心特性**：
- **可重入锁**：同一线程可多次获取锁
- **看门狗 (Watchdog) 自动续期**：防止业务未完成锁过期
- **Lua 脚本保证原子性**：加锁/解锁原子操作
- **支持多种锁类型**：公平锁、读写锁、RedLock

#### 11.5.1 Redisson 锁的内部结构

Redisson 锁在 Redis 中以 **Hash 结构** 存储：

```
Key: "lock:order:100"
Value (Hash):
  {
    "client-uuid:thread-1": "2",   # 客户端标识:线程ID → 重入计数
  }
  TTL: 30000ms (看门狗续期)
```

这种设计支持：
- **可重入性**：同一线程多次获取锁时，计数器递增而非阻塞
- **自动续期**：后台线程定期检查锁状态并延长 TTL
- **线程安全**：每个线程有独立的标识

#### 11.5.2 看门狗 (Watchdog) 机制

看门狗是 Redisson 最核心的特性之一：

```
T1: 客户端获取锁，TTL = 30s（默认 leaseTime）
T2: 看门狗后台线程启动，每 10s（TTL/3）检查一次
T3: 如果客户端仍持有锁（线程存活），续期至 30s
T4: 如果客户端崩溃，线程不再续期，锁在 30s 后自动释放
```

```java
// Redisson 默认行为
RLock lock = redissonClient.getLock("myLock");
lock.lock();  // 默认启用看门狗，TTL=30s，每10s自动续期

// 指定 leaseTime 时，看门狗不生效（锁在指定时间后自动释放）
lock.lock(10, TimeUnit.SECONDS);  // 10秒后自动释放，不续期

// tryLock 也支持看门狗
boolean locked = lock.tryLock(0, -1, TimeUnit.SECONDS);
// waitTime=0 表示不等待
// leaseTime=-1 表示启用看门狗自动续期
```

#### 11.5.3 Redisson 基础使用

**Maven 依赖**：
```xml
<dependency>
    <groupId>org.redisson</groupId>
    <artifactId>redisson</artifactId>
    <version>3.23.0</version>
</dependency>
```

**配置 Redisson 客户端**：
```java
// 单节点模式
Config config = new Config();
config.useSingleServer()
      .setAddress("redis://127.0.0.1:6379")
      .setPassword("yourpassword")
      .setDatabase(0)
      .setConnectionPoolSize(64)
      .setConnectionMinimumIdleSize(10);
RedissonClient redisson = Redisson.create(config);

// 集群模式
Config config = new Config();
config.useClusterServers()
      .addNodeAddress("redis://192.168.1.10:6379")
      .addNodeAddress("redis://192.168.1.11:6379")
      .addNodeAddress("redis://192.168.1.12:6379")
      .setPassword("yourpassword");
RedissonClient redisson = Redisson.create(config);
```

**分布式锁使用**：
```java
public class OrderService {

    @Autowired
    private RedissonClient redissonClient;

    public boolean deductStock(String productId, int quantity) {
        String lockKey = "lock:stock:" + productId;
        RLock lock = redissonClient.getLock(lockKey);

        try {
            // 尝试获取锁：最多等待10秒，锁自动释放时间30秒
            boolean locked = lock.tryLock(10, 30, TimeUnit.SECONDS);
            if (!locked) {
                // 获取锁失败
                return false;
            }

            // 获取锁成功，执行业务逻辑
            int stock = getStockFromDB(productId);
            if (stock < quantity) {
                return false; // 库存不足
            }
            updateStockInDB(productId, stock - quantity);
            return true;

        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return false;
        } finally {
            // 确保释放锁（只有持有锁的线程才能释放）
            if (lock.isHeldByCurrentThread()) {
                lock.unlock();
            }
        }
    }
}
```

#### 11.5.4 Redisson 加锁/解锁 Lua 脚本

**加锁脚本**（简化版）：
```lua
-- KEYS[1]: 锁名称
-- ARGV[1]: 线程标识 (UUID:threadId)
-- ARGV[2]: 过期时间(毫秒)

if redis.call('EXISTS', KEYS[1]) == 0 then
    -- 锁不存在，获取锁
    redis.call('HSET', KEYS[1], ARGV[1], 1)
    redis.call('PEXPIRE', KEYS[1], ARGV[2])
    return nil
end

if redis.call('HEXISTS', KEYS[1], ARGV[1]) == 1 then
    -- 锁存在但属于当前线程，重入计数+1
    redis.call('HINCRBY', KEYS[1], ARGV[1], 1)
    redis.call('PEXPIRE', KEYS[1], ARGV[2])
    return nil
end

-- 锁被其他线程持有，返回剩余过期时间
return redis.call('PTTL', KEYS[1])
```

**解锁脚本**（简化版）：
```lua
-- KEYS[1]: 锁名称
-- ARGV[1]: 线程标识

if redis.call('HEXISTS', KEYS[1], ARGV[1]) == 0 then
    -- 不是当前线程持有，直接返回
    return nil
end

local count = redis.call('HINCRBY', KEYS[1], ARGV[1], -1)
if count > 0 then
    -- 重入次数大于0，刷新过期时间
    redis.call('PEXPIRE', KEYS[1], ARGV[2])
    return 0
else
    -- 重入次数归0，删除锁
    redis.call('DEL', KEYS[1])
    -- 发布锁释放消息
    redis.call('PUBLISH', KEYS[2], ARGV[1])
    return 1
end
```

### 11.6 RedLock 算法（红锁）

Redis 作者 Antirez 提出的 RedLock 算法用于解决单节点 Redis 主从切换时锁丢失的问题。

#### 11.6.1 主从切换锁丢失问题

```
T1: 客户端A在 Master 上获取锁
T2: Master 在将锁同步到 Slave 前宕机
T3: Sentinel 将 Slave 提升为新 Master
T4: 客户端B在新 Master 上请求同一把锁 → 成功！
T5: ❌ 两个客户端同时持有锁，互斥性被破坏
```

#### 11.6.2 RedLock 核心原理

不依赖单个 Redis 实例，而是与 **多个独立的 Redis 节点**（通常 5 个）交互，只有获得**大多数**节点的锁才算成功。

```
┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐
│  Redis 1  │  │  Redis 2  │  │  Redis 3  │  │  Redis 4  │  │  Redis 5  │
│  (独立)   │  │  (独立)   │  │  (独立)   │  │  (独立)   │  │  (独立)   │
└─────┬─────┘  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘
      │               │               │               │               │
      ▼               ▼               ▼               ▼               ▼
   SET NX          SET NX          SET NX          SET NX          SET NX
   成功✓           成功✓           成功✓           失败✗           成功✓

   成功节点数: 4 > 5/2 = 2.5 → 加锁成功！
   实际有效时间 = 预设TTL - 获取锁耗时
```

#### 11.6.3 RedLock 算法步骤

1. **记录开始时间**：获取当前 Unix 毫秒时间戳
2. **依次向 N 个独立 Redis 节点请求加锁**：
   - 使用相同的 key 和唯一 value (UUID)
   - 设置网络超时时间（远小于锁的 TTL，如 50ms）
   - 某节点超时不阻塞，继续下一个
3. **计算获取锁总耗时** = 当前时间 - 开始时间
4. **判断是否成功**（两个条件都满足）：
   - 从超过半数 (N/2 + 1) 节点成功获取锁
   - 总耗时小于锁的 TTL
5. **计算实际有效时间** = TTL - 总耗时
6. **如果失败**：向**所有节点**发起解锁请求（包括未成功的节点，防止部分写入成功）

#### 11.6.4 Redisson RedLock 实现

```java
Config config1 = new Config();
config1.useSingleServer().setAddress("redis://192.168.1.10:6379");
RedissonClient client1 = Redisson.create(config1);

Config config2 = new Config();
config2.useSingleServer().setAddress("redis://192.168.1.11:6379");
RedissonClient client2 = Redisson.create(config2);

Config config3 = new Config();
config3.useSingleServer().setAddress("redis://192.168.1.12:6379");
RedissonClient client3 = Redisson.create(config3);

Config config4 = new Config();
config4.useSingleServer().setAddress("redis://192.168.1.13:6379");
RedissonClient client4 = Redisson.create(config4);

Config config5 = new Config();
config5.useSingleServer().setAddress("redis://192.168.1.14:6379");
RedissonClient client5 = Redisson.create(config5);

// 获取5把锁
RLock lock1 = client1.getLock("orderLock");
RLock lock2 = client2.getLock("orderLock");
RLock lock3 = client3.getLock("orderLock");
RLock lock4 = client4.getLock("orderLock");
RLock lock5 = client5.getLock("orderLock");

// 组成 RedLock
RedissonRedLock redLock = new RedissonRedLock(lock1, lock2, lock3, lock4, lock5);

try {
    // 尝试加锁
    boolean locked = redLock.tryLock(10, 30, TimeUnit.SECONDS);
    if (locked) {
        // 执行业务逻辑
        doBusinessLogic();
    }
} finally {
    redLock.unlock();
}
```

#### 11.6.5 RedLock 的争议

RedLock 在分布式系统社区引发了激烈争论（Redis 作者 antirez vs 分布式系统专家 Martin Kleppmann）：

**Kleppmann 的批评**：
1. **依赖时钟同步**：节点间时钟漂移会导致锁失效
2. **不保证线性一致性**：GC 暂停可能使客户端在持锁期间"冻结"
3. **网络分区下不可靠**：无法在所有情况下保证互斥性

**Antirez 的回应**：
1. 时钟同步在实践中是可接受的（NTP 精度足够）
2. 可以通过增加 fencing token 进一步保证安全
3. 对于大多数场景，RedLock 足够可靠

**实践建议**：

| 场景 | 推荐方案 |
|------|----------|
| 对一致性要求中等，允许最终一致性 | Redisson 单节点锁（默认） |
| 对性能要求高，锁粒度中等 | Redisson 单节点锁 + 看门狗 |
| 对一致性要求高，可接受性能损耗 | Redisson RedLock |
| 需要严格线性一致性 | Zookeeper / etcd 分布式锁 |
| 强一致性不可妥协 | 数据库乐观锁 / 悲观锁 |

### 11.7 分布式锁最佳实践

1. **锁粒度要细**：
   ```java
   // ❌ 锁范围太大
   RLock lock = redissonClient.getLock("stock");
   
   // ✅ 锁粒度细化到商品
   RLock lock = redissonClient.getLock("stock:product:" + productId);
   ```

2. **设置合理的超时时间**：
   ```java
   // 等待时间：根据业务容忍度设置（如3-10秒）
   // 锁持有时间：留足业务执行时间（如30秒）
   // 如果使用看门狗(-1)，则自动续期
   lock.tryLock(5, -1, TimeUnit.SECONDS);
   ```

3. **必须释放锁**：
   ```java
   try {
       if (lock.tryLock(5, 30, TimeUnit.SECONDS)) {
           // 业务逻辑
       }
   } finally {
       if (lock.isHeldByCurrentThread()) {
           lock.unlock();
       }
   }
   ```

4. **引入业务层幂等保护**：
   ```java
   // 即使锁失效，也能通过幂等性保证最终一致性
   String requestId = UUID.randomUUID().toString();
   orderMapper.insertWithRequestId(order, requestId);
   ```

5. **降级策略**：
   ```java
   try {
       if (lock.tryLock(3, 30, TimeUnit.SECONDS)) {
           // 使用 Redis 锁
           doBusiness();
       } else {
           // 降级为数据库乐观锁
           updateWithOptimisticLock();
       }
   } finally {
       if (lock.isHeldByCurrentThread()) {
           lock.unlock();
       }
   }
   ```

---

## 十二、发布订阅与 Stream 消息队列

### 12.1 Pub/Sub 发布订阅

**基本操作**：
```bash
# 订阅频道
SUBSCRIBE news sports

# 模式订阅（通配符）
PSUBSCRIBE news.*

# 发布消息
PUBLISH news "Breaking: Redis 7.0 released!"

# 查看活跃频道
PUBSUB CHANNELS
PUBSUB NUMSUB news          # 查看频道订阅者数量
```

**Python 示例**：
```python
# 发布者
import redis
r = redis.Redis(host='localhost', port=6379)
r.publish('chat_room', 'Hello, everyone!')

# 订阅者
pubsub = r.pubsub()
pubsub.subscribe('chat_room')
for message in pubsub.listen():
    print(f"Received: {message}")
```

**Pub/Sub 局限性**：
- **不保证消息持久化**：订阅者离线时丢失消息
- **不支持 ACK 应答**：无法确认消息是否被消费
- **无消费者组**：不支持多消费者负载均衡

> 对于需要可靠消息传递的场景，请使用 **Redis Stream**。

### 12.2 Stream 消息队列（5.0+）

Stream 是 Redis 5.0 引入的专门用于消息队列的数据类型，解决了 Pub/Sub 的可靠性问题。

**核心特性**：
- **消息持久化**：消息存储在内存中，不会丢失
- **消费者组 (Consumer Group)**：支持多消费者负载均衡
- **消息确认 (ACK)**：消费者确认消息后才会从 PEL 中移除
- **消息回溯**：可按 ID 查询历史消息

**基本操作**：
```bash
# 生产消息（* 表示自动生成ID）
XADD orders * product_id 1001 user_id 2001 amount 99.9
# 返回消息ID: "1672531200000-0"（时间戳-序号）

# 指定 ID 生产
XADD orders 1672531200000-0 product_id 1001 user_id 2001

# 读取消息（从头开始，最多100条）
XRANGE orders - + COUNT 100

# 反向读取
XREVRANGE orders + - COUNT 10

# 创建消费者组（从第一条消息开始消费）
XGROUP CREATE orders order_group $  # $ 表示从最新消息开始
XGROUP CREATE orders order_group 0  # 0 表示从头开始

# 消费者读取消息
XREADGROUP GROUP order_group consumer-1 COUNT 10 BLOCK 5000 STREAMS orders >
# > 表示读取尚未消费的新消息
# 0 表示读取未确认的消息（重启恢复用）

# 确认消息
XACK orders order_group 1672531200000-0

# 查看未确认的消息
XPENDING orders order_group

# 消费者信息
XINFO CONSUMERS orders order_group

# 消息长度
XLEN orders

# 限制 Stream 长度（裁剪旧消息）
XTRIM orders MAXLEN 1000           # 保留最近1000条
XTRIM orders MINID 1672531200000   # 删除ID小于指定值的

# 删除指定消息
XDEL orders 1672531200000-0
```

**消费者组架构**：
```
                    Stream "orders"
   ┌──────────────────────────────────────────────────────┐
   │ msg-0  msg-1  msg-2  msg-3  msg-4  msg-5  msg-6  ... │
   └──────────────────────────────────────────────────────┘
        │                    │              │
   ┌────▼────┐         ┌─────▼─────┐  ┌─────▼─────┐
   │Consumer 1│        │Consumer 2 │  │Consumer 3 │
   │ msg-0    │        │ msg-1     │  │ msg-2     │
   │ msg-3    │        │ msg-4     │  │ msg-5     │
   │ msg-6    │        │           │  │           │
   └──────────┘        └───────────┘  └───────────┘
   PEL (未ACK)           PEL (未ACK)    PEL (未ACK)
```

**Java 消费者示例**：
```java
// 生产消息
Map<String, String> message = new HashMap<>();
message.put("product_id", "1001");
message.put("user_id", "2001");
message.put("amount", "99.9");
StreamMessageId id = redissonClient.getStream("orders").add(message);

// 消费者组消费
RStream<String, String> stream = redissonClient.getStream("orders");
stream.createGroup("order_group", StreamMessageId.ALL);

// 消费者读取
Map<StreamMessageId, Map<String, String>> messages = stream.readGroup(
    "order_group", "consumer-1",
    StreamReadArgs.greaterThan(StreamMessageId.LAST).count(10).timeout(Duration.ofSeconds(5))
);

for (Map.Entry<StreamMessageId, Map<String, String>> entry : messages.entrySet()) {
    try {
        // 处理消息
        processOrder(entry.getValue());
        // 确认消息
        stream.ack("order_group", entry.getKey());
    } catch (Exception e) {
        // 处理失败，消息留在 PEL 中，稍后可重新消费
    }
}
```

### 12.3 延迟队列实现

利用 Sorted Set 实现延迟队列：

```java
// 添加延迟任务（score 为执行时间戳）
public void addDelayTask(String taskId, long delaySeconds) {
    long executeTime = System.currentTimeMillis() + delaySeconds * 1000;
    redisTemplate.opsForZSet().add("delay:queue", taskId, executeTime);
}

// 消费延迟任务
@Scheduled(fixedRate = 1000) // 每秒扫描一次
public void consumeDelayTasks() {
    long now = System.currentTimeMillis();
    // 获取到期的任务
    Set<String> tasks = redisTemplate.opsForZSet()
        .rangeByScore("delay:queue", 0, now, 0, 10);

    if (tasks != null) {
        for (String taskId : tasks) {
            // 使用 ZREM 保证只有一个消费者处理
            Long removed = redisTemplate.opsForZSet().remove("delay:queue", taskId);
            if (removed != null && removed > 0) {
                // 执行任务
                executeTask(taskId);
            }
        }
    }
}
```

---

## 十三、Redis 7.x 新特性

### 13.1 listpack 替代 ziplist

Redis 7.0 中，**listpack** 正式替代 **ziplist**，用于 List、Hash、ZSet 的小数据编码。

**ziplist 的问题**：连锁更新（Cascade Update）
- 修改一个 entry 可能导致后续所有 entry 的偏移量变化
- 极端情况下，一次修改导致 O(N) 的内存重分配

**listpack 的改进**：
- 每个元素只记录自身长度，不记录前驱长度
- 彻底消除连锁更新问题
- 更节省内存，性能更稳定

### 13.2 Multi-Part AOF

Redis 7.0 将 AOF 拆分为：
- **base 文件**：重写时的全量数据（RDB 或 AOF 格式）
- **增量文件 (incr)**：base 之后的增量写命令
- **manifest 文件**：管理 base 和 incr 文件的关系

优势：
- 重写时不阻塞
- 恢复更高效
- 可并行处理增量数据

### 13.3 Function (函数)

Redis 7.0 引入 Function 替代 EVAL/EVALSHA：

```bash
# 注册函数（持久化）
FUNCTION LOAD "#!lua name=mylib
redis.register_function('myfunc', function(keys, args)
    return redis.call('SET', keys[1], args[1])
end)"

# 调用函数
FCALL myfunc 1 mykey myvalue

# 查看已注册函数
FUNCTION LIST

# 删除函数
FUNCTION DELETE mylib
```

与 Lua 脚本的区别：
| 特性 | Lua 脚本 (EVAL) | Function (FCALL) |
|------|-----------------|-------------------|
| 持久化 | 不持久化（需 EVALSHA） | 持久化到 Redis |
| 管理 | 脚本分散 | 集中管理（库/函数） |
| 重启 | 脚本丢失 | 函数保留 |
| 适用场景 | 临时脚本 | 生产环境复用 |

### 13.4 ACLs (Access Control Lists) 增强

Redis 6.0 引入 ACL，7.0 增强：

```bash
# 创建用户
ACL SETUSER developer on >dev_password ~user:* +get +set +hget +hset

# 查看用户列表
ACL USERS

# 查看用户详情
ACL GETUSER developer

# 删除用户
ACL DELUSER developer

# 查看当前用户
ACL WHOAMI

# 保存 ACL 配置到文件
ACL SAVE

# 从文件加载
ACL LOAD
```

ACL 规则语法：
```
on/off               - 启用/禁用用户
>password            - 设置密码
~pattern             - 允许访问的 key 模式
resetkeys            - 清空 key 模式
+command             - 允许执行该命令
-command             - 禁止执行该命令
+@category           - 允许执行该类别命令（如 +@read, +@write）
-@category           - 禁止执行该类别命令
allcommands/+@all   - 允许所有命令
nocommands/-@all     - 禁止所有命令
```

### 13.5 多线程 I/O 增强

Redis 7.0 优化了多线程 I/O 性能：

```bash
# redis.conf
io-threads 4           # I/O 线程数（建议 CPU 核心数的一半）
io-threads-do-reads yes # I/O 线程也处理读操作
```

---

## 十四、运维监控与故障排查

### 14.1 INFO 命令

```bash
INFO                  # 查看所有信息
INFO server           # 服务器信息
INFO clients          # 客户端信息
INFO memory           # 内存信息
INFO persistence      # 持久化信息
INFO stats            # 统计信息
INFO replication      # 复制信息
INFO cpu              # CPU 信息
INFO cluster          # 集群信息
INFO keyspace         # 键空间信息
```

### 14.2 慢查询分析

```bash
# 配置慢查询
CONFIG SET slowlog-log-slower-than 10000   # 阈值：10ms (微秒)
CONFIG SET slowlog-max-len 1000             # 保留最近1000条

# 查看慢查询
SLOWLOG GET 10    # 查看最近10条
SLOWLOG LEN        # 查看慢查询数量
SLOWLOG RESET      # 清空慢查询日志
```

### 14.3 监控命令

```bash
# 监控 Redis 执行的所有命令（调试用，生产环境慎用）
MONITOR

# 查看客户端列表
CLIENT LIST

# 查看 Redis 内部状态
DEBUG SLEEP 0     # 不阻塞，返回 OK
DEBUG OBJECT key  # 查看 key 的内部编码信息

# 查看键的内存占用
MEMORY USAGE key
MEMORY USAGE key SAMPLES 0  # 精确计算

# 内存诊断
MEMORY STATS
MEMORY DOCTOR

# 大 Key 扫描
redis-cli --bigkeys
redis-cli --memkeys    # 扫描内存占用最大的 key

# 热点 Key 扫描（需开启 LFU 模式）
OBJECT FREQ key       # 查看访问频率
redis-cli --hotkeys
```

### 14.4 连接池配置

**Java (Jedis) 连接池**：
```java
JedisPoolConfig poolConfig = new JedisPoolConfig();
poolConfig.setMaxTotal(100);        // 最大连接数
poolConfig.setMaxIdle(30);          // 最大空闲连接
poolConfig.setMinIdle(10);          // 最小空闲连接
poolConfig.setMaxWaitMillis(5000); // 获取连接最大等待时间
poolConfig.setTestOnBorrow(false);  // 获取连接时测试（建议false，避免性能开销）
poolConfig.setTestWhileIdle(true);  // 空闲时测试
poolConfig.setTimeBetweenEvictionRunsMillis(30000); // 空闲检测间隔

JedisPool pool = new JedisPool(poolConfig, "localhost", 6379, 2000, "password");
```

**连接数计算参考**：
```
maxTotal = QPS × 平均命令耗时(秒) × 安全系数(1.5~2)
示例：QPS=5000, 平均耗时=1ms
maxTotal = 5000 × 0.001 × 2 = 10（至少10个连接）
```

### 14.5 关键监控指标

| 指标 | 命令 | 告警阈值 |
|------|------|----------|
| 内存使用率 | `INFO memory` → `used_memory / maxmemory` | > 85% |
| 命中率 | `INFO stats` → `keyspace_hits / (hits + misses)` | < 90% |
| 连接数 | `INFO clients` → `connected_clients` | > maxclients × 80% |
| 慢查询数 | `SLOWLOG LEN` | 持续增长 |
| 主从延迟 | `INFO replication` → `master_repl_offset - slave_repl_offset` | > 1MB |
| 内存碎片率 | `INFO memory` → `mem_fragmentation_ratio` | > 1.5 |
| RDB/AOF 状态 | `INFO persistence` | 有错 |
| 集群状态 | `CLUSTER INFO` → `cluster_state` | 非 ok |

### 14.6 常见问题排查

**问题1：Redis 变慢**

```bash
# 1. 检查慢查询
SLOWLOG GET 10

# 2. 检查大 key
redis-cli --bigkeys

# 3. 检查内存碎片
INFO memory  # 看 mem_fragmentation_ratio

# 4. 检查是否在 RDB/AOF 重写
INFO persistence

# 5. 检查是否使用了阻塞命令
# 避免 KEYS *, FLUSHALL 等命令
```

**问题2：内存持续增长**

```bash
# 1. 查看内存详情
INFO memory

# 2. 扫描大 key
redis-cli --bigkeys

# 3. 检查是否设置了过期时间
# TTL key 检查是否返回 -1（永不过期）

# 4. 检查淘汰策略
CONFIG GET maxmemory-policy

# 5. 检查是否内存碎片过多
MEMORY PURGE  # 手动整理碎片
```

**问题3：主从复制延迟**

```bash
# 1. 检查主从偏移量
INFO replication
# master_repl_offset vs slave_repl_offset

# 2. 增大复制积压缓冲区
CONFIG SET repl-backlog-size 256mb

# 3. 检查网络带宽
# 4. 减少 Master 上的大 key 操作
```

---

## 十五、开发最佳实践与规范

### 15.1 Key 命名规范

```
业务:对象:ID[:字段]
```

| 示例 | 说明 |
|------|------|
| `user:1001` | 用户对象 |
| `user:1001:profile` | 用户资料 |
| `order:2001:detail` | 订单详情 |
| `stock:product:3001` | 商品库存 |
| `cache:api:product:list` | API 缓存 |
| `lock:order:2001` | 订单锁 |
| `rank:daily:20250730` | 日排行榜 |

**命名原则**：
- 使用冒号 `:` 分隔层级
- Key 长度控制在 100 字符内
- 避免特殊字符
- 使用有意义的前缀，便于管理和扫描

### 15.2 Value 设计规范

- 单个 Value 不超过 1MB
- 避免 Hash/List/Set 元素超过 1 万
- 复杂对象使用 Hash 存储，而非 String 存 JSON
- 设置合理的 TTL，避免内存泄漏

### 15.3 命令使用规范

| 规范 | 重要程度 | 说明 |
|------|----------|------|
| 禁用 `KEYS *` | ★★★★★ | 使用 `SCAN` 替代 |
| 避免大 Key 操作 | ★★★★★ | 分批处理 HGETALL、LRANGE 等 |
| 使用 Pipeline 批量操作 | ★★★★★ | 减少网络往返 |
| 合理设置 TTL | ★★★★☆ | 避免内存泄漏 |
| 避免复杂 Lua 脚本 | ★★★★☆ | 脚本应毫秒级完成 |
| 使用 Hash Tag 保证集群事务 | ★★★★☆ | 集群模式下 key 在同一槽 |
| 禁用 `FLUSHALL / FLUSHDB` | ★★★★★ | 生产环境禁用 |

### 15.4 数据一致性策略

**Cache Aside Pattern（旁路缓存，最常用）**：
```java
// 读
data = cache.get(key);
if (data == null) {
    data = db.get(key);
    cache.set(key, data, ttl);
}

// 写
db.update(key, newValue);
cache.del(key);  // 删除缓存，而非更新（避免并发问题）
```

**为什么删除缓存而非更新缓存？**
1. 避免并发场景下缓存与数据库不一致
2. 懒加载，节省内存
3. 有些缓存值计算复杂，更新开销大

**双删策略（延迟双删）**：
```java
// 1. 先删缓存
cache.del(key);
// 2. 更新数据库
db.update(key, newValue);
// 3. 延迟再删一次（防止读旧数据回填缓存）
executor.schedule(() -> cache.del(key), 500, TimeUnit.MILLISECONDS);
```

### 15.5 序列化选择

| 序列化方式 | 性能 | 体积 | 可读性 | 推荐场景 |
|-----------|------|------|--------|----------|
| JSON | 中 | 大 | 好 | 对象较小、需可读 |
| Protobuf | 高 | 小 | 差 | 对象较大、高性能 |
| MsgPack | 高 | 中 | 差 | 通用高性能 |
| JDK | 低 | 大 | 差 | 不推荐 |

### 15.6 客户端选择

| 语言 | 推荐客户端 | 说明 |
|------|-----------|------|
| Java | **Lettuce** (Spring Boot 默认) | 异步、线程安全 |
| Java | **Jedis** | 轻量、同步 |
| Java | **Redisson** | 分布式锁、集合等高级功能 |
| Python | redis-py | 官方推荐 |
| Go | go-redis | 高性能 |
| Node.js | ioredis | 支持 Cluster/Pipeline |

### 15.7 生产环境检查清单

- [ ] 设置 `requirepass` 密码认证
- [ ] 配置 ACL 用户权限分离
- [ ] 同时开启 RDB + AOF 持久化
- [ ] 设置合理的 `maxmemory` 和淘汰策略
- [ ] 禁用危险命令（FLUSHALL、KEYS、CONFIG）
- [ ] 配置慢查询日志
- [ ] 监控内存使用率、命中率、连接数
- [ ] 使用连接池管理客户端连接
- [ ] 集群模式使用 Hash Tag 保证多键操作
- [ ] 定期备份 RDB 文件
- [ ] 主从/哨兵/集群配置 `masterauth`
- [ ] 监控主从复制延迟
- [ ] 开启内存碎片自动整理

---

## 附录：参考资料

### 官方文档
- Redis 官方文档: https://redis.io/docs/
- Redis Commands: https://redis.io/commands/
- Redis Cluster Specification: https://redis.io/docs/reference/cluster-spec/

### 参考资料
1. Redis Cluster 集群搭建与深度解析 - https://blog.csdn.net/qq_42287536/article/details/147549474
2. Redis 持久化与高可用实战 - https://blog.csdn.net/2401_88299394/article/details/154216002
3. Redis 分布式锁 Redisson 深度解析 - https://blog.csdn.net/weixin_43290370/article/details/154689081
4. RedLock 与 Redisson 实现分布式锁 - https://blog.csdn.net/xiaofeng10330111/article/details/133828594
5. 深度剖析 Redisson 分布式锁 - https://devpress.csdn.net/v1/article/detail/149481811
6. Redis 缓存三大问题详解 - https://juejin.cn/post/7563126048506888211
7. Redis 集群全景指南 - https://jamhihi.blog.csdn.net/article/details/149908088
8. 2025 Redis 深度面试宝典 - https://zhangmenghan.blog.csdn.net/article/details/153487164
9. Redis Pipeline 性能优化 - https://besthub.dev/articles/how-redis-pipeline-can-boost-performance-3-12-and-impress-interviewers-74183c962480
10. Redis 缓存设计与性能优化 - https://blog.51cto.com/u_16213569/14412687
11. Redis 内存陡增深度复盘 - https://developer.aliyun.com/article/1701226
12. Redis 数据结构与底层实现 - https://pengline.cn/2025/12/fb61cae088544f86a4209a47b2ca6a3d

---

> **文档说明**：本文档基于 Redis 7.x 版本编写，参考了网络上的最新技术资料和最佳实践。文档中的代码示例以 Java 和 Python 为主，适用于大多数后端开发场景。如需了解更多细节，请查阅官方文档或参考资料中的链接。
