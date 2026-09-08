# Spring Boot 3 + MyBatis-Plus 技术文档（基础版）

> 版本：Spring Boot 3.2+ / MyBatis-Plus 3.5.17 / JDK 17+
> 最后更新：2026年7月
> 参考来源：Spring 官方文档、MyBatis-Plus 官方文档、CSDN/掘金等 15+ 篇技术文章

---

## 目录

1. [Spring Boot 3 概述与核心新特性](#1-spring-boot-3-概述与核心新特性)
2. [环境搭建与项目创建](#2-环境搭建与项目创建)
3. [核心注解与自动配置原理](#3-核心注解与自动配置原理)
4. [配置文件管理](#4-配置文件管理)
5. [Web 开发基础](#5-web-开发基础)
6. [参数校验与全局异常处理](#6-参数校验与全局异常处理)
7. [日志配置](#7-日志配置)
8. [MyBatis-Plus 简介与集成](#8-mybatis-plus-简介与集成)
9. [MyBatis-Plus 基础 CRUD](#9-mybatis-plus-基础-crud)
10. [条件构造器 Wrapper](#10-条件构造器-wrapper)
11. [分页查询](#11-分页查询)
12. [代码生成器](#12-代码生成器)
13. [事务管理](#13-事务管理)
14. [基础项目实战](#14-基础项目实战)

---

## 1. Spring Boot 3 概述与核心新特性

### 1.1 什么是 Spring Boot？

Spring Boot 是 Spring 生态的核心框架，它基于"**约定大于配置**"的设计理念，简化了 Spring 应用的初始搭建和开发过程。开发者只需关注业务代码，框架会自动完成大量的配置工作。

Spring Boot = Spring Framework + 嵌入式服务器（Tomcat/Jetty/Undertow）- XML 配置 - 代码生成

### 1.2 Spring Boot 3.x 核心新特性

| 特性 | 说明 |
|------|------|
| **Java 17 基线** | 最低要求 JDK 17，支持 JDK 21 LTS |
| **Jakarta EE 10** | `javax.*` 全部迁移至 `jakarta.*`，这是最大破坏性变更 |
| **原生镜像支持** | 集成 Spring Native，通过 GraalVM 编译为原生可执行文件 |
| **可观测性增强** | Micrometer Tracing 替代 Spring Cloud Sleuth，内置 OpenTelemetry 支持 |
| **虚拟线程** | JDK 21 虚拟线程支持，极大提升并发处理能力 |
| **ProblemDetail** | 支持 RFC 7807 标准的错误响应格式 |
| **AOT 编译** | Ahead-of-Time 编译优化，启动时间缩短 50%+ |

### 1.3 Spring Boot 架构核心

```
┌─────────────────────────────────────────────────────┐
│                  Spring Boot 应用                     │
├─────────────────────────────────────────────────────┤
│  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │
│  │  Controller│  │  Service  │  │   Repository     │  │
│  │   (Web)  │  │ (Business)│  │   (Data Access)  │  │
│  └──────────┘  └──────────┘  └──────────────────┘  │
├─────────────────────────────────────────────────────┤
│              Spring Boot 自动配置层                   │
│  ┌─────────────────────────────────────────────┐   │
│  │  AutoConfiguration  │  Condition  │  Properties │   │
│  └─────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────┤
│              Spring Framework 核心                    │
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐   │
│  │ IOC  │ │ AOP  │ │ MVC  │ │ TX   │ │ Data │   │
│  └──────┘ └──────┘ └──────┘ └──────┘ └──────┘   │
├─────────────────────────────────────────────────────┤
│              嵌入式 Servlet 容器 (Tomcat)              │
├─────────────────────────────────────────────────────┤
│                    JVM (JDK 17+)                     │
└─────────────────────────────────────────────────────┘
```

---

## 2. 环境搭建与项目创建

### 2.1 环境要求

| 工具 | 版本要求 | 说明 |
|------|---------|------|
| JDK | 17+ (推荐 21 LTS) | Spring Boot 3.x 最低要求 JDK 17 |
| Maven | 3.8.8+ | 低版本可能导致依赖下载失败 |
| Gradle | 7.6.4+ / 8.4+ | 可选，推荐 Maven |
| IDE | IntelliJ IDEA 2023.2+ | 自带 Spring Initializr |
| MySQL | 8.0+ | 适配最新 JDBC 驱动 |

### 2.2 三种创建方式

**方式一：Spring Initializr（官方推荐）**

访问 [https://start.spring.io/](https://start.spring.io/) 配置参数：

```
Project: Maven
Language: Java
Spring Boot: 3.2.x
Group: com.example
Artifact: demo
Java: 17
Dependencies: Spring Web, MyBatis Framework, MySQL Driver, Lombok, DevTools
```

**方式二：IDEA 内置创建**

File → New → Project → Spring Initializr → 配置同上

**方式三：手动 Maven 项目**

```xml
<!-- pom.xml 示例 -->
<parent>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-parent</artifactId>
    <version>3.2.6</version>
    <relativePath/>
</parent>

<properties>
    <java.version>17</java.version>
</properties>

<dependencies>
    <!-- Web 场景启动器 -->
    <dependency>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-web</artifactId>
    </dependency>
    <!-- 测试 -->
    <dependency>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-test</artifactId>
        <scope>test</scope>
    </dependency>
    <!-- Lombok -->
    <dependency>
        <groupId>org.projectlombok</groupId>
        <artifactId>lombok</artifactId>
        <optional>true</optional>
    </dependency>
</dependencies>

<build>
    <plugins>
        <plugin>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-maven-plugin</artifactId>
        </plugin>
    </plugins>
</build>
```

### 2.3 主启动类与 Hello World

```java
package com.example.demo;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@SpringBootApplication
public class DemoApplication {
    public static void main(String[] args) {
        SpringApplication.run(DemoApplication.class, args);
    }
}

@RestController
class HelloController {
    @GetMapping("/hello")
    public String hello() {
        return "Hello, Spring Boot 3!";
    }
}
```

### 2.4 项目标准结构

```
src/
├── main/
│   ├── java/com/example/demo/
│   │   ├── DemoApplication.java          # 启动类
│   │   ├── controller/                    # 控制器层
│   │   ├── service/                       # 服务接口
│   │   │   └── impl/                      # 服务实现
│   │   ├── mapper/                        # MyBatis Mapper 接口
│   │   ├── entity/                        # 实体类 / POJO
│   │   ├── dto/                           # 数据传输对象
│   │   ├── config/                        # 配置类
│   │   └── common/                        # 公共类（工具、常量、异常）
│   └── resources/
│       ├── application.yml                # 主配置文件
│       ├── application-dev.yml            # 开发环境配置
│       ├── application-prod.yml           # 生产环境配置
│       └── mapper/                        # MyBatis XML 映射文件
└── test/
    └── java/com/example/demo/             # 测试代码
```

---

## 3. 核心注解与自动配置原理

### 3.1 `@SpringBootApplication` 注解解析

```java
@SpringBootApplication  // 复合注解，等价于以下三个:
// @SpringBootConfiguration  → 标记为配置类
// @EnableAutoConfiguration  → 启用自动配置
// @ComponentScan             → 组件扫描
public class DemoApplication { }
```

### 3.2 自动配置原理（3 步流程）

```
步骤1: 启动时加载配置
  └── SpringFactoriesLoader 读取
      META-INF/spring/org.springframework.boot.autoconfigure.
      AutoConfiguration.imports 文件
      (Spring Boot 3.x 替代了旧版 spring.factories)

步骤2: 条件装配（@Conditional）
  └── 根据 classpath 中的类、配置属性、Bean 存在情况
      决定是否启用某个自动配置
      例: @ConditionalOnClass(DataSource.class)
          @ConditionalOnProperty(name = "spring.datasource.url")
          @ConditionalOnMissingBean

步骤3: 按需创建 Bean
  └── 满足条件的自动配置类被加载，
      向容器注册 DataSource、JdbcTemplate、TransactionManager 等 Bean
```

### 3.3 常用核心注解

| 注解 | 作用 | 层级 |
|------|------|------|
| `@SpringBootApplication` | 标记启动类，复合注解 | 应用 |
| `@RestController` | = @Controller + @ResponseBody | Controller |
| `@RequestMapping` | 映射请求路径 | Controller |
| `@GetMapping / @PostMapping / @PutMapping / @DeleteMapping` | RESTful 风格请求映射 | Controller |
| `@PathVariable` | 获取 URL 路径变量 | Controller |
| `@RequestParam` | 获取请求参数 | Controller |
| `@RequestBody` | 获取请求体 JSON | Controller |
| `@Service` | 标记 Service 层组件 | Service |
| `@Autowired` | 自动注入依赖 | 通用 |
| `@Configuration` | 标记配置类 | 配置 |
| `@Bean` | 声明 Bean | 配置 |
| `@Value` | 注入配置文件属性 | 通用 |
| `@ConfigurationProperties` | 类型安全配置绑定 | 配置 |

### 3.4 组件扫描规则

```
Spring Boot 默认扫描启动类所在包及其所有子包

示例:
启动类: com.example.demo.DemoApplication
扫描范围: com.example.demo.** (所有子包)

如果 Controller/Service 在 com.example.other 包下：
→ 不会被扫描，需要添加 @ComponentScan("com.example")
```

---

## 4. 配置文件管理

### 4.1 application.yml 基础配置

```yaml
# 服务器配置
server:
  port: 8080
  servlet:
    context-path: /api    # 上下文路径

# Spring 配置
spring:
  application:
    name: demo-app
    
  # 数据库配置
  datasource:
    url: jdbc:mysql://localhost:3306/mydb?useUnicode=true&characterEncoding=utf-8&serverTimezone=Asia/Shanghai
    username: root
    password: yourpassword
    driver-class-name: com.mysql.cj.jdbc.Driver
    hikari:                          # HikariCP 连接池（默认）
      maximum-pool-size: 20
      minimum-idle: 5
      idle-timeout: 300000
      connection-timeout: 20000
      
  # Jackson 配置
  jackson:
    date-format: yyyy-MM-dd HH:mm:ss
    time-zone: GMT+8
    default-property-inclusion: non_null
    
# MyBatis-Plus 配置
mybatis-plus:
  mapper-locations: classpath*:/mapper/**/*.xml
  type-aliases-package: com.example.demo.entity
  configuration:
    map-underscore-to-camel-case: true   # 下划线转驼峰
    log-impl: org.apache.ibatis.logging.stdout.StdOutImpl  # SQL 日志
  global-config:
    db-config:
      id-type: auto                      # 主键自增
      logic-delete-field: deleted        # 逻辑删除字段
      logic-delete-value: 1
      logic-not-delete-value: 0
```

### 4.2 多环境配置

```yaml
# application.yml - 主配置
spring:
  profiles:
    active: dev    # 默认激活开发环境
```

```yaml
# application-dev.yml - 开发环境
server:
  port: 8080
spring:
  datasource:
    url: jdbc:mysql://localhost:3306/dev_db
    username: dev_user
    password: dev_pass
logging:
  level:
    com.example: DEBUG
```

```yaml
# application-prod.yml - 生产环境
server:
  port: 8080
spring:
  datasource:
    url: ${DB_URL}                     # 从环境变量读取
    username: ${DB_USERNAME}
    password: ${DB_PASSWORD}
logging:
  level:
    com.example: WARN
```

### 4.3 属性注入方式

```java
// 方式一: @Value 注入单个属性
@Value("${server.port}")
private int port;

// 方式二: @ConfigurationProperties 批量绑定（推荐）
@Data
@Component
@ConfigurationProperties(prefix = "app")
public class AppConfig {
    private String name;
    private String version;
}
// application.yml:
// app:
//   name: my-app
//   version: 1.0.0
```

---

## 5. Web 开发基础

### 5.1 RESTful API 设计

```java
@RestController
@RequestMapping("/api/users")
@RequiredArgsConstructor
public class UserController {
    
    private final UserService userService;
    
    // GET    /api/users          → 查询用户列表
    @GetMapping
    public List<User> list() {
        return userService.list();
    }
    
    // GET    /api/users/{id}     → 查询单个用户
    @GetMapping("/{id}")
    public User getById(@PathVariable Long id) {
        return userService.getById(id);
    }
    
    // POST   /api/users          → 创建用户
    @PostMapping
    public User create(@RequestBody User user) {
        return userService.create(user);
    }
    
    // PUT    /api/users/{id}     → 更新用户
    @PutMapping("/{id}")
    public User update(@PathVariable Long id, @RequestBody User user) {
        user.setId(id);
        return userService.update(user);
    }
    
    // DELETE /api/users/{id}     → 删除用户
    @DeleteMapping("/{id}")
    public void delete(@PathVariable Long id) {
        userService.delete(id);
    }
}
```

### 5.2 统一响应格式

```java
@Data
@NoArgsConstructor
@AllArgsConstructor
public class ApiResponse<T> {
    private int code;           // 状态码
    private String message;     // 消息
    private T data;             // 数据
    private long timestamp;     // 时间戳
    
    public static <T> ApiResponse<T> success(T data) {
        return new ApiResponse<>(200, "操作成功", data, System.currentTimeMillis());
    }
    
    public static <T> ApiResponse<T> success(String message, T data) {
        return new ApiResponse<>(200, message, data, System.currentTimeMillis());
    }
    
    public static <T> ApiResponse<T> error(int code, String message) {
        return new ApiResponse<>(code, message, null, System.currentTimeMillis());
    }
    
    public static <T> ApiResponse<T> error(String message) {
        return new ApiResponse<>(500, message, null, System.currentTimeMillis());
    }
}
```

### 5.3 三种参数接收方式

```java
@RestController
@RequestMapping("/api/demo")
public class DemoController {
    
    // 1. URL 路径参数
    @GetMapping("/path/{id}")
    public String pathVariable(@PathVariable Long id) {
        return "id: " + id;
    }
    
    // 2. 查询参数 ?key=value
    @GetMapping("/query")
    public String requestParam(@RequestParam String name,
                               @RequestParam(defaultValue = "1") int page) {
        return "name: " + name + ", page: " + page;
    }
    
    // 3. JSON 请求体
    @PostMapping("/body")
    public User requestBody(@RequestBody User user) {
        return user;
    }
}
```

---

## 6. 参数校验与全局异常处理

### 6.1 参数校验注解

```java
@Data
public class UserCreateDTO {
    
    @NotBlank(message = "用户名不能为空")
    @Size(min = 2, max = 20, message = "用户名长度需在2-20之间")
    private String username;
    
    @NotBlank(message = "密码不能为空")
    @Size(min = 6, max = 30, message = "密码长度需在6-30之间")
    private String password;
    
    @Email(message = "邮箱格式不正确")
    private String email;
    
    @Min(value = 0, message = "年龄不能为负数")
    @Max(value = 150, message = "年龄不能超过150")
    private Integer age;
    
    @Pattern(regexp = "^1[3-9]\\d{9}$", message = "手机号格式不正确")
    private String phone;
}
```

Controller 中使用：

```java
@PostMapping
public ApiResponse<User> create(@Valid @RequestBody UserCreateDTO dto) {
    User user = userService.create(dto);
    return ApiResponse.success(user);
}
```

### 6.2 全局异常处理

```java
@RestControllerAdvice
@Slf4j
public class GlobalExceptionHandler {
    
    // 处理参数校验异常
    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ApiResponse<?> handleValidation(MethodArgumentNotValidException e) {
        String message = e.getBindingResult().getFieldErrors().stream()
                .map(error -> error.getField() + ": " + error.getDefaultMessage())
                .collect(Collectors.joining("; "));
        log.warn("参��校验失败: {}", message);
        return ApiResponse.error(400, message);
    }
    
    // 处理业务异常
    @ExceptionHandler(BusinessException.class)
    public ApiResponse<?> handleBusiness(BusinessException e) {
        log.warn("业务异常: [{}] {}", e.getCode(), e.getMessage());
        return ApiResponse.error(e.getCode(), e.getMessage());
    }
    
    // 处理系统未知异常
    @ExceptionHandler(Exception.class)
    public ApiResponse<?> handleSystem(Exception e) {
        log.error("系统异常", e);
        return ApiResponse.error(500, "系统繁忙，请稍后再试");
    }
}
```

业务异常定义：

```java
public class BusinessException extends RuntimeException {
    private final int code;
    
    public BusinessException(int code, String message) {
        super(message);
        this.code = code;
    }
    
    public BusinessException(String message) {
        this(500, message);
    }
    
    public int getCode() { return code; }
}
```

---

## 7. 日志配置

### 7.1 application.yml 日志配置

```yaml
logging:
  level:
    root: INFO                          # 全局日志级别
    com.example.demo: DEBUG             # 指定包日志级别
    com.example.demo.mapper: TRACE      # MyBatis Mapper 日志级别
  file:
    path: ./logs                        # 日志文件目录
    name: ./logs/app.log                # 日志文件名
  pattern:
    console: "%d{yyyy-MM-dd HH:mm:ss} [%thread] %-5level %logger{50} - %msg%n"
    file: "%d{yyyy-MM-dd HH:mm:ss} [%thread] %-5level %logger{50} - %msg%n"
  logback:
    rolling-policy:
      max-file-size: 10MB               # 单个日志文件最大大小
      max-history: 30                   # 保留天数
```

### 7.2 代码中使用日志

```java
@RestController
@Slf4j   // Lombok 自动生成 log 对象
public class UserController {
    
    @GetMapping("/users")
    public List<User> list() {
        log.info("查询用户列表");
        log.debug("调试信息: 当前时间 {}", LocalDateTime.now());
        try {
            return userService.list();
        } catch (Exception e) {
            log.error("查询用户列表失败", e);
            throw e;
        }
    }
}
```

---

## 8. MyBatis-Plus 简介与集成

### 8.1 MyBatis-Plus 概述

MyBatis-Plus（简称 MP）是 MyBatis 的增强工具，在 MyBatis 的基础上"**只做增强不做改变**"，简化 CRUD 操作，提供丰富的开箱即用功能。

| 特性 | 说明 |
|------|------|
| **无侵入** | 引入后不会对现有工程产生影响 |
| **CRUD 便捷** | 只需简单配置即可进行单表 CRUD 操作 |
| **条件构造器** | 强大的 Wrapper，支持 Lambda 表达式 |
| **分页插件** | 物理分页，自动拦截 SQL |
| **代码生成器** | 一键生成 Entity/Mapper/Service/Controller |
| **逻辑删除** | 注解配置，自动追加删除条件 |
| **自动填充** | 创建时间/更新时间等字段自动填充 |
| **乐观锁** | @Version 注解，自动版本控制 |

### 8.2 Maven 依赖

```xml
<!-- MyBatis-Plus Starter（已包含 MyBatis、JDBC 等） -->
<dependency>
    <groupId>com.baomidou</groupId>
    <artifactId>mybatis-plus-spring-boot3-starter</artifactId>
    <version>3.5.17</version>
</dependency>

<!-- MySQL 驱动 -->
<dependency>
    <groupId>com.mysql</groupId>
    <artifactId>mysql-connector-j</artifactId>
    <scope>runtime</scope>
</dependency>
```

### 8.3 实体类与表映射

```java
@Data
@TableName("user")    // 指定数据库表名
public class User {
    
    @TableId(type = IdType.AUTO)     // 主键，自增
    private Long id;
    
    @TableField("username")          // 指定数据库字段名
    private String username;
    
    private String password;
    
    @TableField("email")
    private String email;
    
    @TableField(value = "phone", exist = true)
    private String phone;
    
    @TableField(exist = false)       // 数据库表中不存在的字段
    private String token;
    
    @TableField(fill = FieldFill.INSERT)    // 插入时自动填充
    private LocalDateTime createTime;
    
    @TableField(fill = FieldFill.INSERT_UPDATE) // 插入和更新时自动填充
    private LocalDateTime updateTime;
}
```

**主键策略 IdType：**

| 策略 | 说明 |
|------|------|
| `AUTO` | 数据库自增 |
| `NONE` | 无状态（默认雪花算法） |
| `INPUT` | 手动输入 |
| `ASSIGN_ID` | 雪花算法（Long） |
| `ASSIGN_UUID` | UUID（String） |

---

## 9. MyBatis-Plus 基础 CRUD

### 9.1 BaseMapper 接口

```java
@Mapper
public interface UserMapper extends BaseMapper<User> {
    // 继承 BaseMapper<User> 后自动拥有所有单表 CRUD 方法
    // 可继续扩展自定义方法
    @Select("SELECT * FROM user WHERE age > #{age}")
    List<User> selectByAgeGreaterThan(@Param("age") int age);
}
```

### 9.2 常用 Mapper 操作示例

```java
@SpringBootTest
class UserMapperTest {
    
    @Autowired
    private UserMapper userMapper;
    
    // ==================== 插入 ====================
    @Test
    void insert() {
        User user = new User();
        user.setUsername("张三");
        user.setAge(25);
        user.setEmail("zhangsan@example.com");
        int rows = userMapper.insert(user);
        // 插入后 user.getId() 自动回填主键值
        System.out.println("插入成功, ID: " + user.getId());
    }
    
    // ==================== 查询 ====================
    @Test
    void select() {
        // 根据 ID 查询
        User user = userMapper.selectById(1L);
        
        // 根据多个 ID 批量查询
        List<User> users = userMapper.selectBatchIds(Arrays.asList(1L, 2L, 3L));
        
        // 根据条件查询单条（超过1条会报错）
        User one = userMapper.selectOne(
            new LambdaQueryWrapper<User>().eq(User::getUsername, "张三")
        );
        
        // 查询列表
        List<User> list = userMapper.selectList(null);
        
        // 查询总数
        Long count = userMapper.selectCount(
            new LambdaQueryWrapper<User>().gt(User::getAge, 18)
        );
    }
    
    // ==================== 更新 ====================
    @Test
    void update() {
        // 根据主键更新（只更新非 null 字段）
        User user = new User();
        user.setId(1L);
        user.setAge(30);           // 只更新 age
        userMapper.updateById(user);
        
        // 根据条件更新
        userMapper.update(null,
            new LambdaUpdateWrapper<User>()
                .set(User::getStatus, 0)
                .eq(User::getAge, 60)
        );
    }
    
    // ==================== 删除 ====================
    @Test
    void delete() {
        // 根据 ID 删除（若配置逻辑删除，则执行 UPDATE）
        userMapper.deleteById(1L);
        
        // 批量删除
        userMapper.deleteBatchIds(Arrays.asList(1L, 2L, 3L));
        
        // 条件删除（物理删除，慎用！）
        userMapper.delete(
            new LambdaQueryWrapper<User>().lt(User::getAge, 18)
        );
    }
}
```

### 9.3 IService 接口（推��方式）

Service 接口定义：

```java
public interface UserService extends IService<User> {
    // 可自定义业务方法
    List<User> getUsersByAgeRange(Integer minAge, Integer maxAge);
}
```

Service 实现类：

```java
@Service
public class UserServiceImpl extends ServiceImpl<UserMapper, User> implements UserService {
    
    @Override
    public List<User> getUsersByAgeRange(Integer minAge, Integer maxAge) {
        return baseMapper.selectUsersByAge(minAge, maxAge);
    }
}
```

**IService 主要方法：**

```java
// 插入
userService.save(user);
userService.saveBatch(userList);              // 批量插入
userService.saveOrUpdate(user);               // 存在则更新，否则插入

// 查询
User user = userService.getById(1L);
List<User> list = userService.list();
List<User> byIds = userService.listByIds(ids);
long count = userService.count();

// 更新
userService.updateById(user);
userService.updateBatchById(userList);
userService.update(user, wrapper);

// 删除（逻辑删除）
userService.removeById(1L);
userService.removeByIds(idList);
userService.remove(wrapper);
```

---

## 10. 条件构造器 Wrapper

### 10.1 QueryWrapper vs LambdaQueryWrapper

```java
// 方式一: QueryWrapper（使用字符串列名）
QueryWrapper<User> wrapper1 = new QueryWrapper<>();
wrapper1.eq("username", "张三")
        .ge("age", 18)
        .orderByDesc("create_time");

// 方式二: LambdaQueryWrapper（推荐，类型安全，编译期检查）
LambdaQueryWrapper<User> wrapper2 = new LambdaQueryWrapper<>();
wrapper2.eq(User::getUsername, "张三")
        .ge(User::getAge, 18)
        .orderByDesc(User::getCreateTime);
```

### 10.2 常用条件方法

| 方法 | 条件 | SQL 等效 |
|------|------|---------|
| `eq(R column, Object val)` | 等于 = | `column = val` |
| `ne(R column, Object val)` | 不等于 != | `column != val` |
| `gt(R column, Object val)` | 大于 > | `column > val` |
| `ge(R column, Object val)` | 大于等于 >= | `column >= val` |
| `lt(R column, Object val)` | 小于 < | `column < val` |
| `le(R column, Object val)` | 小于等于 <= | `column <= val` |
| `between(R column, Object v1, Object v2)` | 在之间 | `column BETWEEN v1 AND v2` |
| `like(R column, Object val)` | 模糊查询 | `column LIKE '%val%'` |
| `in(R column, Collection<?> coll)` | 在集合中 | `column IN (v1, v2, ...)` |
| `isNull(R column)` | 为空 | `column IS NULL` |
| `orderByAsc(R column)` | 升序排列 | `ORDER BY column ASC` |
| `orderByDesc(R column)` | 降序排列 | `ORDER BY column DESC` |
| `groupBy(R column)` | 分组 | `GROUP BY column` |
| `having(String sqlHaving)` | HAVING | `HAVING sqlHaving` |

### 10.3 条件构造器进阶用法

```java
// ============ 链式调用 ============
LambdaQueryWrapper<User> wrapper = Wrappers.<User>lambdaQuery()
    .eq(User::getStatus, 1)
    .like(User::getUsername, "张")
    .between(User::getAge, 18, 60)
    .orderByDesc(User::getCreateTime);

// ============ 动态条件（条件判断） ============
public List<User> queryUsers(String username, Integer minAge, Integer maxAge) {
    LambdaQueryWrapper<User> wrapper = new LambdaQueryWrapper<>();
    wrapper.eq(StringUtils.isNotBlank(username), User::getUsername, username)
           .ge(minAge != null, User::getAge, minAge)
           .le(maxAge != null, User::getAge, maxAge);
    // 只有条件参数不为空时才拼接条件
    return userMapper.selectList(wrapper);
}

// ============ 指定查询字段（避免查大字段） ============
LambdaQueryWrapper<User> selectWrapper = Wrappers.<User>lambdaQuery()
    .select(User::getId, User::getUsername, User::getAge)
    .eq(User::getStatus, 1);
List<User> users = userMapper.selectList(selectWrapper);

// ============ 自定义 SQL 条件（子查询等） ============
wrapper.apply("age > (SELECT AVG(age) FROM user)");
wrapper.last("LIMIT 10");                          // 拼接到最后
wrapper.exists("SELECT 1 FROM order WHERE user_id = user.id"); // EXISTS
```

### 10.4 UpdateWrapper 条件更新

```java
LambdaUpdateWrapper<User> updateWrapper = Wrappers.<User>lambdaUpdate()
    .set(User::getStatus, 0)         // SET status = 0
    .set(User::getAge, null)          // SET age = NULL
    .eq(User::getStatus, 1)           // WHERE status = 1
    .lt(User::getCreateTime, LocalDateTime.now().minusDays(90)); // AND create_time < 90天前

userMapper.update(null, updateWrapper);
// 等价 SQL: UPDATE user SET status=0, age=NULL WHERE status=1 AND create_time < '...'
```

---

## 11. 分页查询

### 11.1 分页插件配置

```java
@Configuration
public class MybatisPlusConfig {
    
    @Bean
    public MybatisPlusInterceptor mybatisPlusInterceptor() {
        MybatisPlusInterceptor interceptor = new MybatisPlusInterceptor();
        
        // 添加分页插件
        PaginationInnerInterceptor paginationInterceptor = new PaginationInnerInterceptor();
        paginationInterceptor.setDbType(DbType.MYSQL);          // 数据库类型
        paginationInterceptor.setMaxLimit(500L);                // 单页最大记录数
        paginationInterceptor.setOverflow(true);                // 溢出总页数后回到首页
        interceptor.addInnerInterceptor(paginationInterceptor);
        
        return interceptor;
    }
}
```

### 11.2 分页查询使用

```java
// Mapper 层分页
IPage<User> userPage = userMapper.selectPage(
    new Page<>(1, 10),                    // 第1页，每页10条
    new LambdaQueryWrapper<User>()
        .eq(User::getStatus, 1)
        .orderByDesc(User::getCreateTime)
);

System.out.println("总记录数: " + userPage.getTotal());
System.out.println("总页数: " + userPage.getPages());
System.out.println("当前页数据: " + userPage.getRecords());

// Service 层分页
Page<User> page = new Page<>(1, 10);
userService.page(page, wrapper);

// 自定义 SQL 分页
@Select("SELECT * FROM user WHERE age > #{age}")
IPage<User> selectByAgeWithPage(Page<User> page, @Param("age") int age);
```

### 11.3 PageHelper 风格分页

```java
// MyBatis-Plus 也支持 PageHelper 风格
Page<User> page = PageHelper.startPage(1, 10);
List<User> list = userMapper.selectList(null);
// 获取分页信息
System.out.println("总记录数: " + page.getTotal());
```

---

## 12. 代码生成器

### 12.1 新版代码生成器（3.5.6+）

```java
public class CodeGenerator {
    
    public static void main(String[] args) {
        String url = "jdbc:mysql://localhost:3306/mydb?serverTimezone=Asia/Shanghai";
        String username = "root";
        String password = "yourpassword";
        String parentPackage = "com.example.demo";
        String moduleName = "system";
        
        FastAutoGenerator.create(url, username, password)
            // ==================== 全局配置 ====================
            .globalConfig(builder -> {
                builder.author("Admin")                      // 作者名
                       .outputDir(System.getProperty("user.dir") 
                                + "/src/main/java")          // 输出目录
                       .disableOpenDir()                     // 生成后不打开目录
                       .commentDate("yyyy-MM-dd");           // 注释日期
            })
            // ==================== 包配置 ====================
            .packageConfig(builder -> {
                builder.parent(parentPackage)                // 父包名
                       .moduleName(moduleName)               // 模块名
                       .entity("entity")                     // Entity 包名
                       .mapper("mapper")                     // Mapper 包名
                       .service("service")                   // Service 包名
                       .serviceImpl("service.impl")          // ServiceImpl 包名
                       .controller("controller")             // Controller 包名
                       .xml("mapper");                       // XML 目录
            })
            // ==================== 策略配置 ====================
            .strategyConfig(builder -> {
                builder.addInclude("user", "role", "permission")  // 需要生成的表名
                       .addTablePrefix("tb_", "t_")               // 过滤表前缀
                       
                       // Entity 策略
                       .entityBuilder()
                       .enableLombok()                             // 启用 Lombok
                       .enableTableFieldAnnotation()              // 生成字段注解
                       .enableFileOverride()                      // 覆盖已有文件
                       .logicDeleteColumnName("deleted")          // 逻辑删��字段
                       .enableChainModel()                        // 链式调用
                       
                       // Mapper 策略
                       .mapperBuilder()
                       .enableBaseResultMap()                     // 生成 ResultMap
                       .enableBaseColumnList()                    // 生成 BaseColumnList
                       .enableMapperAnnotation()                  // 添加 @Mapper
                       
                       // Service 策略
                       .serviceBuilder()
                       .formatServiceFileName("%sService")        // Service 命名
                       .formatServiceImplFileName("%sServiceImpl")
                       
                       // Controller 策略
                       .controllerBuilder()
                       .enableRestStyle()                         // @RestController
                       .enableHyphenStyle()                       // URL 驼峰转连字符
                       .formatFileName("%sController");
            })
            // ==================== 模板引擎 ====================
            .templateEngine(new FreemarkerTemplateEngine())
            .execute();
    }
}
```

### 12.2 代码生成器 Maven 依赖

```xml
<!-- 代码生成器 -->
<dependency>
    <groupId>com.baomidou</groupId>
    <artifactId>mybatis-plus-generator</artifactId>
    <version>3.5.17</version>
</dependency>
<!-- 模板引擎（Freemarker） -->
<dependency>
    <groupId>org.freemarker</groupId>
    <artifactId>freemarker</artifactId>
</dependency>
```

### 12.3 MyBatisX IDEA 插件（推荐）

在 IDEA 插件市场搜索 "MybatisX"，安装后可实现：

- Mapper 与 XML 之间跳转
- 代码生成（支持达梦、Oracle 等多种数据库）
- 方法名自动补全
- 可视化编辑 SQL

---

## 13. 事务管理

### 13.1 声明式事务 `@Transactional`

```java
@Service
public class OrderService {
    
    // 默认事务属性: 只对 RuntimeException 和 Error 回滚
    @Transactional
    public void createOrder(Order order) {
        orderMapper.insert(order);
        // 如果下面抛异常，上面插入的数据会回滚
        orderItemMapper.insertBatch(order.getItems());
    }
    
    // 指定回滚的异常类型
    @Transactional(rollbackFor = Exception.class)
    public void updateOrder(Order order) {
        // ...
    }
    
    // 只读事务（性能优化，数据库可针对性优化）
    @Transactional(readOnly = true)
    public Order getOrderById(Long id) {
        return orderMapper.selectById(id);
    }
    
    // 指定超时时间（秒）
    @Transactional(timeout = 30)
    public void batchProcess() { }
}
```

### 13.2 事务传播行为

| 传播行为 | 说明 |
|---------|------|
| `REQUIRED`（默认） | 有事务则加入，无则新建 |
| `REQUIRES_NEW` | 总是新建事务，挂起当前事务 |
| `NESTED` | 嵌套事务，内部回滚不影响外部 |
| `SUPPORTS` | 有事务则加入，无则非事务运行 |
| `NOT_SUPPORTED` | 总是非事务运行，挂起当前事务 |
| `MANDATORY` | 必须在事务中，否则抛异常 |
| `NEVER` | 必须在非事务中，否则抛异常 |

```java
@Transactional(propagation = Propagation.REQUIRES_NEW)
public void createLog(OrderLog log) {
    // 独立事务，即使外部事务回滚，日志也会提交
    orderLogMapper.insert(log);
}
```

### 13.3 事务使用注意事项

> **核心原则：只有通过 Spring 代理对象调用的方法，`@Transactional` 才会生效**

```java
@Service
public class UserService {
    
    // ❌ 错误：类内部直接调用，事务不生效
    public void wrongMethod() {
        this.transactionalMethod();  // 直接调用，不经过代理
    }
    
    @Transactional
    public void transactionalMethod() {
        // 事务不会生效
    }
    
    // ✅ 正确：注入自身或放到另一个 Service
    @Autowired
    private UserService self;  // 注入代理对象
    
    public void correctMethod() {
        self.transactionalMethod();  // 通过代理调用，事务生效
    }
}
```

**其他注意事项：**

- `@Transactional` 方法必须是 public
- 数据库表引擎必须支持事务（如 InnoDB）
- 避免在事务中进行远程调用、文件操作等耗时操作
- 捕获异常后如果不抛出，事务不会回滚

---

## 14. 基础项目实战

### 14.1 完整项目结构

```
src/main/java/com/example/demo/
├── DemoApplication.java
├── entity/
│   └── User.java
├── dto/
│   ├── UserCreateDTO.java
│   └── UserQueryDTO.java
├── mapper/
│   └── UserMapper.java
├── service/
│   ├── UserService.java
│   └── impl/
│       └── UserServiceImpl.java
├── controller/
│   └── UserController.java
├── config/
│   ├── MybatisPlusConfig.java
│   └── WebConfig.java
└── common/
    ├── ApiResponse.java
    ├── BusinessException.java
    └── GlobalExceptionHandler.java
```

### 14.2 完整 Controller 示例

```java
@RestController
@RequestMapping("/api/users")
@RequiredArgsConstructor
@Slf4j
public class UserController {
    
    private final UserService userService;
    
    /**
     * 分页查询用户
     */
    @GetMapping
    public ApiResponse<IPage<User>> page(UserQueryDTO query) {
        log.info("分页查询用户: {}", query);
        LambdaQueryWrapper<User> wrapper = Wrappers.<User>lambdaQuery()
            .like(StringUtils.isNotBlank(query.getUsername()), 
                  User::getUsername, query.getUsername())
            .eq(query.getStatus() != null, User::getStatus, query.getStatus())
            .ge(query.getMinAge() != null, User::getAge, query.getMinAge())
            .le(query.getMaxAge() != null, User::getAge, query.getMaxAge())
            .orderByDesc(User::getCreateTime);
        
        Page<User> page = new Page<>(query.getPage(), query.getSize());
        IPage<User> result = userService.page(page, wrapper);
        return ApiResponse.success(result);
    }
    
    /**
     * 根据 ID 查询用户
     */
    @GetMapping("/{id}")
    public ApiResponse<User> getById(@PathVariable Long id) {
        User user = userService.getById(id);
        if (user == null) {
            throw new BusinessException(404, "用户不存在");
        }
        return ApiResponse.success(user);
    }
    
    /**
     * 创建用户
     */
    @PostMapping
    public ApiResponse<User> create(@Valid @RequestBody UserCreateDTO dto) {
        User user = new User();
        BeanUtils.copyProperties(dto, user);
        userService.save(user);
        log.info("创建用户成功: ID={}", user.getId());
        return ApiResponse.success(user);
    }
    
    /**
     * 更新用户
     */
    @PutMapping("/{id}")
    public ApiResponse<User> update(@PathVariable Long id, @RequestBody User user) {
        user.setId(id);
        userService.updateById(user);
        return ApiResponse.success(user);
    }
    
    /**
     * 删除用户
     */
    @DeleteMapping("/{id}")
    public ApiResponse<Void> delete(@PathVariable Long id) {
        userService.removeById(id);
        return ApiResponse.success(null);
    }
}
```

### 14.3 查询 DTO 示例

```java
@Data
public class UserQueryDTO {
    private String username;           // 用户名（模糊查询）
    private Integer status;            // 状态
    private Integer minAge;            // 最小年龄
    private Integer maxAge;            // 最大年龄
    
    @Min(1)
    private Integer page = 1;          // 页码，默认第1页
    
    @Min(1) @Max(100)
    private Integer size = 10;         // 每页条数，默认10条
}
```

---

## 结尾

本文档基于 Spring Boot 3.2+ 和 MyBatis-Plus 3.5.17 编写，涵盖了从环境搭建到项目实战的全链路基础内容。掌握了这些知识，你已经可以独立完成大部分企业级 Java 后端的开发工作。

> 进阶内容（多数据源、分布式事务、安全认证、Docker 部署、性能优化等）请参阅《Spring Boot 3 + MyBatis-Plus 技术文档（进阶版）》。

---

*参考来源：Spring 官方文档、MyBatis-Plus 官方文档 (baomidou.com)、CSDN、掘金、阿里云开发者社区等 15+ 篇技术文章*
