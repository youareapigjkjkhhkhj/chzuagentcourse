# Spring Boot 3 + MyBatis-Plus 技术文档（进阶版）

> 版本：Spring Boot 3.2+ / MyBatis-Plus 3.5.17 / JDK 17+
> 最后更新：2026年7月
> 参考来源：Spring 官方文档、MyBatis-Plus 官方文档、CSDN/掘金/博客园等 20+ 篇技术文章

---

## 目录

1. [Spring Boot 3 高级特性](#1-spring-boot-3-高级特性)
2. [类型安全配置与多环境管理](#2-类型安全配置与多环境管理)
3. [拦截器与过滤器](#3-拦截器与过滤器)
4. [统一响应与异常处理进阶](#4-统一响应与异常处理进阶)
5. [Spring Security + JWT 安全认证](#5-spring-security--jwt-安全认证)
6. [MyBatis-Plus 高级特性](#6-mybatis-plus-高级特性)
7. [多数据源管理](#7-多数据源管理)
8. [动态表名与多租户](#8-动态表名与多租户)
9. [自定义 SQL 注入器与插件扩展](#9-自定义-sql-注入器与插件扩展)
10. [Redis 缓存集成](#10-redis-缓存集成)
11. [异步处理与线程池优化](#11-异步处理与线程池优化)
12. [可观测性 - Actuator + Prometheus + Grafana](#12-可观测性---actuator--prometheus--grafana)
13. [分布式事务 Seata](#13-分布式事务-seata)
14. [Docker 容器化部署](#14-docker-容器化部署)
15. [生产级最佳实践与性能优化](#15-生产级最佳实践与性能优化)

---

## 1. Spring Boot 3 高级特性

### 1.1 Spring Boot 3.x 新特性回顾

| 特性 | 说明 |
|------|------|
| **Java 17 基线** | 最低 JDK 17，推荐 JDK 21 LTS（支持虚拟线程） |
| **Jakarta EE 10** | `javax.*` → `jakarta.*` 全部迁移 |
| **GraalVM 原生镜像** | AOT 编译，启动时间从秒级降至毫秒级 |
| **虚拟线程** | JDK 21 Project Loom 支持，极大简化并发编程 |
| **可观测性** | Micrometer Tracing + OpenTelemetry 集成 |
| **ProblemDetail** | RFC 7807 标准错误格式 |
| **HttpExchange** | 声明式 HTTP 客户端接口 |

### 1.2 GraalVM 原生镜像

提升启动速度 10 倍+，降低内存占用 60%+：

```xml
<!-- pom.xml 添加插件 -->
<plugin>
    <groupId>org.graalvm.buildtools</groupId>
    <artifactId>native-maven-plugin</artifactId>
</plugin>
```

```bash
# 构建原生镜像
./mvnw -Pnative native:compile

# 直接运行（无需 JVM）
./target/demo-app
```

**注意事项：**
- 反射、动态代理、资源加载需要预配置 RuntimeHints
- 所有 Bean 必须在编译期确定（不能有运行时动态注册）
- 某些第三方库可能不完全兼容

### 1.3 虚拟线程（Virtual Threads）

JDK 21 引入虚拟线程，解决传统线程池的阻塞瓶颈：

```yaml
# application.yml
spring:
  threads:
    virtual:
      enabled: true     # 开启虚拟线程
      max-threads: -1   # -1 表示不限制
```

```java
// 传统线程池
@Bean
public Executor taskExecutor() {
    return Executors.newFixedThreadPool(200);
}

// 虚拟线程（无需线程池，按需创建）
@Bean
public Executor taskExecutor() {
    return Executors.newVirtualThreadPerTaskExecutor();
}
```

**虚拟线程适用场景：**
- IO 密集型任务（数据库查询、HTTP 调用、文件读写）
- 高并发 Web 请求处理
- 消息处理

**不适用场景：**
- CPU 密集型计算（虚拟线程不提升计算速度）
- 需要线程局部变量(timed)且不能迁移的场景

---

## 2. 类型安全配置与多环境管理

### 2.1 `@ConfigurationProperties` 类型安全配置

```java
// 定义配置类
@Data
@Component
@ConfigurationProperties(prefix = "app")
public class AppProperties {
    /** 应用名称 */
    private String name;
    /** 应用版本 */
    private String version;
    /** 上传配置 */
    private Upload upload = new Upload();
    /** 线程池配置 */
    private ThreadPool threadPool = new ThreadPool();
    
    @Data
    public static class Upload {
        private String path;
        private long maxSize;
        private List<String> allowedTypes;
    }
    
    @Data
    public static class ThreadPool {
        private int core = 10;
        private int max = 50;
        private int queue = 200;
    }
}
```

```yaml
# application.yml
app:
  name: demo-app
  version: 1.0.0
  upload:
    path: /data/uploads
    max-size: 10485760  # 10MB
    allowed-types:
      - jpg
      - png
      - pdf
  thread-pool:
    core: 20
    max: 100
    queue: 500
```

```java
// 使用
@RestController
@RequiredArgsConstructor
public class ConfigController {
    private final AppProperties appProperties;
    
    @GetMapping("/config")
    public AppProperties getConfig() {
        return appProperties;
    }
}
```

### 2.2 Maven 多环境打包

```xml
<!-- pom.xml -->
<profiles>
    <profile>
        <id>dev</id>
        <properties>
            <profiles.active>dev</profiles.active>
        </properties>
        <activation>
            <activeByDefault>true</activeByDefault>
        </activation>
    </profile>
    <profile>
        <id>prod</id>
        <properties>
            <profiles.active>prod</profiles.active>
        </properties>
    </profile>
</profiles>

<build>
    <resources>
        <resource>
            <directory>src/main/resources</directory>
            <filtering>true</filtering>
        </resource>
    </resources>
</build>
```

```bash
# 开发环境打包
mvn clean package -P dev

# 生产环境打包
mvn clean package -P prod
```

### 2.3 配置优先级

Spring Boot 配置加载优先级（由高到低）：

```
1.  命令行参数（--server.port=9090）
2.  JNDI 属性
3.  Java 系统属性（System.getProperties()）
4.  操作系统环境变量（SERVER_PORT）
5.  application-{profile}.yml（外部）
6.  application-{profile}.yml（内部）
7.  application.yml（外部）
8.  application.yml（内部）
9.  @PropertySource 注解
10. SpringApplication.setDefaultProperties()
```

---

## 3. 拦截器与过滤器

### 3.1 过滤器 Filter

```java
@Component
@Slf4j
public class RequestLoggingFilter implements Filter {
    
    @Override
    public void doFilter(ServletRequest request, ServletResponse response, 
                         FilterChain chain) throws IOException, ServletException {
        HttpServletRequest httpRequest = (HttpServletRequest) request;
        long startTime = System.currentTimeMillis();
        
        log.info("请求进入: {} {}", httpRequest.getMethod(), httpRequest.getRequestURI());
        
        chain.doFilter(request, response);
        
        long duration = System.currentTimeMillis() - startTime;
        log.info("请求完成: {} {} - {}ms", 
                 httpRequest.getMethod(), httpRequest.getRequestURI(), duration);
    }
}
```

**Filter vs Interceptor：**

| 维度 | Filter | Interceptor |
|------|--------|-------------|
| 容器 | Servlet 容器 | Spring 容器 |
| 时机 | 进入 Servlet 之前/之后 | Handler 执行前后 |
| 能力 | 只能使用 request/response | 可访问 Handler、ModelAndView |
| 典型用途 | 编码、CORS、XSS 过滤 | 日志、权限、性能监控 |

### 3.2 拦截器 Interceptor

```java
@Component
@Slf4j
public class AuthInterceptor implements HandlerInterceptor {
    
    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, 
                             Object handler) {
        String token = request.getHeader("Authorization");
        if (StringUtils.isBlank(token)) {
            throw new BusinessException(401, "未登录");
        }
        // 验证 token 逻辑...
        return true;  // true 放行，false 拦截
    }
    
    @Override
    public void postHandle(HttpServletRequest request, HttpServletResponse response,
                          Object handler, ModelAndView modelAndView) {
        // Controller 执行后、视图渲染前
    }
    
    @Override
    public void afterCompletion(HttpServletRequest request, HttpServletResponse response,
                               Object handler, Exception ex) {
        // 请求完成后清理资源
    }
}
```

拦截器注册：

```java
@Configuration
public class WebConfig implements WebMvcConfigurer {
    
    @Autowired
    private AuthInterceptor authInterceptor;
    
    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        registry.addInterceptor(authInterceptor)
                .addPathPatterns("/api/**")            // 拦截路径
                .excludePathPatterns("/api/auth/**",    // 排除路径
                                    "/api/public/**");
    }
}
```

---

## 4. 统一响应与异常处理进阶

### 4.1 统一响应增强

```java
// 增强版统一响应
@Data
public class ApiResponse<T> {
    private int code;
    private String message;
    private T data;
    private Long timestamp;
    private String traceId;        // 链路追踪 ID
    
    public static <T> ApiResponse<T> success(T data) {
        ApiResponse<T> resp = new ApiResponse<>();
        resp.code = 200;
        resp.message = "操作成功";
        resp.data = data;
        resp.timestamp = System.currentTimeMillis();
        resp.traceId = MDC.get("traceId");
        return resp;
    }
    
    public static <T> ApiResponse<T> error(int code, String message) {
        ApiResponse<T> resp = new ApiResponse<>();
        resp.code = code;
        resp.message = message;
        resp.timestamp = System.currentTimeMillis();
        resp.traceId = MDC.get("traceId");
        return resp;
    }
}
```

### 4.2 接口响应统一包装（ResponseBodyAdvice）

```java
@RestControllerAdvice
public class ResponseAdvice implements ResponseBodyAdvice<Object> {
    
    @Override
    public boolean supports(MethodParameter returnType, 
                           Class<? extends HttpMessageConverter<?>> converterType) {
        // 如果已经包装过，则不重复包装
        return !returnType.getParameterType().equals(ApiResponse.class);
    }
    
    @Override
    public Object beforeBodyWrite(Object body, MethodParameter returnType,
                                 MediaType selectedContentType,
                                 Class<? extends HttpMessageConverter<?>> selectedConverterType,
                                 ServerHttpRequest request, ServerHttpResponse response) {
        // String 特殊处理（会被 StringHttpMessageConverter 处理）
        if (body instanceof String) {
            return JSON.toJSONString(ApiResponse.success(body));
        }
        return ApiResponse.success(body);
    }
}
```

### 4.3 分层异常设计

```java
// 错误码枚举
@Getter
@AllArgsConstructor
public enum ErrorCode {
    // 1xxx: 业务参数错误
    PARAM_INVALID(1001, "参数无效"),
    USER_NOT_FOUND(1002, "用户不存在"),
    
    // 2xxx: 认证授权错误
    TOKEN_EXPIRED(2001, "令牌过期"),
    UNAUTHORIZED(2002, "未授权访问"),
    FORBIDDEN(2003, "权限不足"),
    
    // 5xxx: 系统错误
    SYSTEM_ERROR(5000, "系统繁忙"),
    DB_ERROR(5001, "数据库错误"),
    ;
    
    private final int code;
    private final String message;
}

// 业务异常
@Getter
public class BusinessException extends RuntimeException {
    private final int code;
    private final String details;
    
    public BusinessException(ErrorCode errorCode) {
        super(errorCode.getMessage());
        this.code = errorCode.getCode();
        this.details = null;
    }
    
    public BusinessException(ErrorCode errorCode, String details) {
        super(errorCode.getMessage());
        this.code = errorCode.getCode();
        this.details = details;
    }
}
```

---

## 5. Spring Security + JWT 安全认证

### 5.1 Maven 依赖

```xml
<dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-security</artifactId>
</dependency>
<dependency>
    <groupId>io.jsonwebtoken</groupId>
    <artifactId>jjwt-api</artifactId>
    <version>0.12.5</version>
</dependency>
<dependency>
    <groupId>io.jsonwebtoken</groupId>
    <artifactId>jjwt-impl</artifactId>
    <version>0.12.5</version>
    <scope>runtime</scope>
</dependency>
<dependency>
    <groupId>io.jsonwebtoken</groupId>
    <artifactId>jjwt-jackson</artifactId>
    <version>0.12.5</version>
    <scope>runtime</scope>
</dependency>
```

### 5.2 JWT 工具类

```java
@Component
public class JwtUtil {
    
    @Value("${jwt.secret:your-256-bit-secret-key-here-minimum-32-characters}")
    private String secret;
    
    @Value("${jwt.expiration:86400000}")
    private long expiration;   // 24小时
    
    private SecretKey getSigningKey() {
        return Keys.hmacShaKeyFor(secret.getBytes(StandardCharsets.UTF_8));
    }
    
    /**
     * 生成 JWT Token
     */
    public String generateToken(String username, List<String> roles) {
        Date now = new Date();
        return Jwts.builder()
            .subject(username)
            .claim("roles", roles)
            .issuedAt(now)
            .expiration(new Date(now.getTime() + expiration))
            .signWith(getSigningKey())
            .compact();
    }
    
    /**
     * 解析 Token 中的用户名
     */
    public String getUsernameFromToken(String token) {
        return parseClaims(token).getSubject();
    }
    
    /**
     * 验证 Token 是否有效
     */
    public boolean validateToken(String token) {
        try {
            parseClaims(token);
            return true;
        } catch (JwtException | IllegalArgumentException e) {
            return false;
        }
    }
    
    private Claims parseClaims(String token) {
        return Jwts.parser()
            .verifyWith(getSigningKey())
            .build()
            .parseSignedClaims(token)
            .getPayload();
    }
}
```

### 5.3 JWT 认证过滤器

```java
@Component
@RequiredArgsConstructor
public class JwtAuthenticationFilter extends OncePerRequestFilter {
    
    private final JwtUtil jwtUtil;
    
    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response,
                                    FilterChain filterChain) throws ServletException, IOException {
        String authHeader = request.getHeader("Authorization");
        
        if (authHeader != null && authHeader.startsWith("Bearer ")) {
            String token = authHeader.substring(7);
            
            if (jwtUtil.validateToken(token)) {
                String username = jwtUtil.getUsernameFromToken(token);
                
                // 将认证信息设置到 SecurityContext
                UsernamePasswordAuthenticationToken authentication =
                    new UsernamePasswordAuthenticationToken(username, null, 
                        Collections.singletonList(new SimpleGrantedAuthority("ROLE_USER")));
                SecurityContextHolder.getContext().setAuthentication(authentication);
            }
        }
        
        filterChain.doFilter(request, response);
    }
}
```

### 5.4 Security 配置

```java
@Configuration
@EnableWebSecurity
@EnableMethodSecurity   // 启用方法级安全注解 @PreAuthorize
@RequiredArgsConstructor
public class SecurityConfig {
    
    private final JwtAuthenticationFilter jwtAuthFilter;
    
    @Bean
    public SecurityFilterChain securityFilterChain(HttpSecurity http) throws Exception {
        http
            // 禁用 CSRF（API 服务不需要）
            .csrf(AbstractHttpConfigurer::disable)
            // 无状态会话
            .sessionManagement(session -> 
                session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
            // 路由权限配置
            .authorizeHttpRequests(auth -> auth
                .requestMatchers("/api/auth/**", "/api/public/**").permitAll()
                .requestMatchers("/api/admin/**").hasRole("ADMIN")
                .anyRequest().authenticated()
            )
            // 添加 JWT 过滤器
            .addFilterBefore(jwtAuthFilter, UsernamePasswordAuthenticationFilter.class);
        
        return http.build();
    }
    
    @Bean
    public PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder();
    }
    
    @Bean
    public AuthenticationManager authenticationManager(
            AuthenticationConfiguration config) throws Exception {
        return config.getAuthenticationManager();
    }
}
```

### 5.5 方法级权限控制

```java
@RestController
@RequestMapping("/api/admin")
public class AdminController {
    
    @PreAuthorize("hasRole('ADMIN')")
    @GetMapping("/users")
    public List<User> getAllUsers() {
        return userService.list();
    }
    
    @PreAuthorize("hasRole('ADMIN') or #userId == authentication.principal.id")
    @DeleteMapping("/users/{userId}")
    public void deleteUser(@PathVariable Long userId) {
        userService.removeById(userId);
    }
}
```

---

## 6. MyBatis-Plus 高级特性

### 6.1 逻辑删除

```java
@Data
@TableName("user")
public class User {
    @TableId
    private Long id;
    
    @TableLogic      // 逻辑删除注解
    private Integer deleted;  // 0-未删除 1-已删除
}
```

```yaml
# application.yml 全局配置
mybatis-plus:
  global-config:
    db-config:
      logic-delete-field: deleted      # 逻辑删除字段名
      logic-delete-value: 1            # 逻辑已删除值
      logic-not-delete-value: 0        # 逻辑未删除值
```

**效果：**
```java
// 执行删除
userMapper.deleteById(1L);
// → SQL: UPDATE user SET deleted=1 WHERE id=1 AND deleted=0

// 查询自动追加 deleted=0 条件
userMapper.selectList(null);
// → SQL: SELECT * FROM user WHERE deleted=0
```

### 6.2 乐观锁

用于解决并发更新冲突问题：

```java
@Data
public class Product {
    @TableId
    private Long id;
    private String name;
    private Integer stock;
    
    @Version       // 乐观锁版本字段
    private Integer version;
}
```

插件注册：

```java
@Bean
public MybatisPlusInterceptor mybatisPlusInterceptor() {
    MybatisPlusInterceptor interceptor = new MybatisPlusInterceptor();
    // 乐观锁插件
    interceptor.addInnerInterceptor(new OptimisticLockerInnerInterceptor());
    return interceptor;
}
```

**原理：**
```java
// 更新时自动追加 version 条件
Product product = productService.getById(1L);  // version=1
product.setStock(product.getStock() - 1);
productService.updateById(product);
// → SQL: UPDATE product SET stock=99, version=2 
//        WHERE id=1 AND version=1
// 如果其他线程已修改（version 变成了 2），此更新返回 0 行，说明并发冲突
```

### 6.3 自动填充

```java
@Component
public class MyMetaObjectHandler implements MetaObjectHandler {
    
    @Override
    public void insertFill(MetaObject metaObject) {
        this.strictInsertFill(metaObject, "createTime", LocalDateTime.class, 
                              LocalDateTime.now());
        this.strictInsertFill(metaObject, "updateTime", LocalDateTime.class, 
                              LocalDateTime.now());
        this.strictInsertFill(metaObject, "deleted", Integer.class, 0);
    }
    
    @Override
    public void updateFill(MetaObject metaObject) {
        this.strictUpdateFill(metaObject, "updateTime", LocalDateTime.class, 
                              LocalDateTime.now());
    }
}
```

```java
// 实体类字段标记
@TableField(fill = FieldFill.INSERT)
private LocalDateTime createTime;

@TableField(fill = FieldFill.INSERT_UPDATE)
private LocalDateTime updateTime;
```

### 6.4 字段类型处理器（TypeHandler）

适用于 JSON 字段自动序列化：

```java
// 自定义 TypeHandler：将 List<String> 转为 JSON 存入数据库
@MappedTypes(List.class)
@MappedJdbcTypes(JdbcType.VARCHAR)
public class ListStringTypeHandler extends BaseTypeHandler<List<String>> {
    
    @Override
    public void setNonNullParameter(PreparedStatement ps, int i, 
                                    List<String> parameter, JdbcType jdbcType) {
        ps.setString(i, JSON.toJSONString(parameter));
    }
    
    @Override
    public List<String> getNullableResult(ResultSet rs, String columnName) 
            throws SQLException {
        String json = rs.getString(columnName);
        return JSON.parseArray(json, String.class);
    }
    
    @Override
    public List<String> getNullableResult(ResultSet rs, int columnIndex) 
            throws SQLException {
        String json = rs.getString(columnIndex);
        return JSON.parseArray(json, String.class);
    }
    
    @Override
    public List<String> getNullableResult(CallableStatement cs, int columnIndex) 
            throws SQLException {
        String json = cs.getString(columnIndex);
        return JSON.parseArray(json, String.class);
    }
}
```

```java
@Data
public class User {
    @TableId
    private Long id;
    
    @TableField(typeHandler = ListStringTypeHandler.class)
    private List<String> hobbies;    // ["reading","swimming"] → JSON 存入数据库
}
```

---

## 7. 多数据源管理

### 7.1 使用 Dynamic-Datasource 组件

```xml
<dependency>
    <groupId>com.baomidou</groupId>
    <artifactId>dynamic-datasource-spring-boot3-starter</artifactId>
    <version>4.3.1</version>
</dependency>
```

### 7.2 配置多数据源

```yaml
spring:
  datasource:
    dynamic:
      primary: master                          # 默认主数据源
      strict: false                            # 非严格模式
      datasource:
        # 主数据源（写）
        master:
          url: jdbc:mysql://localhost:3306/master_db?serverTimezone=Asia/Shanghai
          username: root
          password: master123
          driver-class-name: com.mysql.cj.jdbc.Driver
        # 从数据源（读）
        slave:
          url: jdbc:mysql://localhost:3306/slave_db?serverTimezone=Asia/Shanghai
          username: root
          password: slave123
          driver-class-name: com.mysql.cj.jdbc.Driver
        # Oracle 数据源
        oracle:
          url: jdbc:oracle:thin:@localhost:1521/ORCL
          username: scott
          password: tiger
          driver-class-name: oracle.jdbc.OracleDriver
```

### 7.3 动态切换数据源

```java
@Service
public class UserService extends ServiceImpl<UserMapper, User> {
    
    // 方式一: 注解切换
    @DS("master")           // 强制使用 master 数据源
    @Transactional
    public void createUser(User user) {
        baseMapper.insert(user);
    }
    
    @DS("slave")            // 使用 slave 阅读数据源
    public List<User> listUsers() {
        return baseMapper.selectList(null);
    }
}

// 方式二: 编程式切换
@RestController
public class TestController {
    
    @GetMapping("/switch")
    public String testSwitch() {
        DynamicDataSourceContextHolder.push("oracle");
        // 执行业务...
        DynamicDataSourceContextHolder.poll();
        return "ok";
    }
}
```

### 7.4 读写分离方案

```java
// AOP 实现自动读写分离
@Aspect
@Component
@Slf4j
public class DataSourceAspect {
    
    @Pointcut("execution(* com.example..*Service.get*(..)) || "
            + "execution(* com.example..*Service.list*(..)) || "
            + "execution(* com.example..*Service.select*(..)) || "
            + "execution(* com.example..*Service.find*(..)) || "
            + "execution(* com.example..*Service.query*(..))")
    public void readPointcut() {}
    
    @Before("readPointcut()")
    public void setReadDataSource() {
        DynamicDataSourceContextHolder.push("slave");
    }
    
    @After("readPointcut()")
    public void clearDataSource() {
        DynamicDataSourceContextHolder.poll();
    }
}
```

---

## 8. 动态表名与多租户

### 8.1 动态表名

适用于按日期/租户分表的场景：

```java
@Component
public class MybatisPlusConfig {
    
    @Bean
    public MybatisPlusInterceptor mybatisPlusInterceptor() {
        MybatisPlusInterceptor interceptor = new MybatisPlusInterceptor();
        
        // 动态表名插件
        DynamicTableNameInnerInterceptor dynamicTableNameInterceptor = 
            new DynamicTableNameInnerInterceptor();
        dynamicTableNameInterceptor.setTableNameHandler((sql, tableName) -> {
            // 获取当前月份作为表后缀
            String month = DateUtil.format(LocalDate.now(), "yyyyMM");
            return tableName + "_" + month;  // user → user_202607
        });
        interceptor.addInnerInterceptor(dynamicTableNameInterceptor);
        
        return interceptor;
    }
}
```

### 8.2 多租户隔离

SaaS 系统中实现不同租户的数据隔离：

```java
@Component
public class MybatisPlusConfig {
    
    @Bean
    public MybatisPlusInterceptor mybatisPlusInterceptor() {
        MybatisPlusInterceptor interceptor = new MybatisPlusInterceptor();
        
        // 多租户插件
        TenantLineInnerInterceptor tenantInterceptor = new TenantLineInnerInterceptor();
        tenantInterceptor.setTenantLineHandler(new TenantLineHandler() {
            @Override
            public Expression getTenantId() {
                // 从当前上下文获取租户 ID
                Long tenantId = TenantContextHolder.getTenantId();
                return new LongValue(tenantId);
            }
            
            @Override
            public String getTenantIdColumn() {
                return "tenant_id";   // 租户字段名
            }
            
            @Override
            public boolean ignoreTable(String tableName) {
                // 忽略不需要租户隔离的表
                return "sys_config".equalsIgnoreCase(tableName);
            }
        });
        interceptor.addInnerInterceptor(tenantInterceptor);
        
        return interceptor;
    }
}
```

```java
// 租户上下文持有者
public class TenantContextHolder {
    private static final ThreadLocal<Long> CONTEXT = new ThreadLocal<>();
    
    public static void setTenantId(Long tenantId) {
        CONTEXT.set(tenantId);
    }
    
    public static Long getTenantId() {
        return CONTEXT.get();
    }
    
    public static void clear() {
        CONTEXT.remove();
    }
}
```

**效果：**
```sql
-- 原始 SQL
SELECT * FROM user WHERE status = 1

-- 插件增强后
SELECT * FROM user WHERE status = 1 AND tenant_id = 1001
```

### 8.3 插件执行顺序

多个插件同时使用时，需要注意执行顺序：

```java
MybatisPlusInterceptor interceptor = new MybatisPlusInterceptor();

// 顺序建议：
// 1. 多租户 → 先拦截改写
interceptor.addInnerInterceptor(new TenantLineInnerInterceptor());
// 2. 动态表名
interceptor.addInnerInterceptor(new DynamicTableNameInnerInterceptor());
// 3. 分页 → 对改写后的 SQL 放分页
interceptor.addInnerInterceptor(new PaginationInnerInterceptor());
// 4. 乐观锁
interceptor.addInnerInterceptor(new OptimisticLockerInnerInterceptor());
// 5. 防止全表更新
interceptor.addInnerInterceptor(new BlockAttackInnerInterceptor());
```

---

## 9. 自定义 SQL 注入器与插件扩展

### 9.1 自定义 BaseMapper 方法

自定义通用方法定义：

```java
// 定义自定义方法接口
public interface BaseCommonMapper<T> extends BaseMapper<T> {
    
    /**
     * 全表物理删除（慎用）
     */
    int deleteAll();
    
    /**
     * 批量插入（忽略已存在的记录）
     */
    int insertIgnoreBatch(@Param("list") List<T> list);
}
```

SQL 方法类：

```java
public class DeleteAllMethod extends AbstractMethod {
    
    @Override
    public MappedStatement injectMappedStatement(Class<?> mapperClass, 
                                                  Class<?> modelClass, 
                                                  TableInfo tableInfo) {
        String sql = "DELETE FROM " + tableInfo.getTableName();
        SqlSource sqlSource = languageDriver.createSqlSource(configuration, sql, modelClass);
        return addDeleteMappedStatement(mapperClass, "deleteAll", sqlSource);
    }
}
```

自定义注入器：

```java
public class MySqlInjector extends DefaultSqlInjector {
    
    @Override
    public List<AbstractMethod> getMethodList(Configuration configuration,
                                              Class<?> mapperClass, 
                                              TableInfo tableInfo) {
        List<AbstractMethod> methodList = super.getMethodList(configuration, mapperClass, tableInfo);
        // 添加自定义方法
        methodList.add(new DeleteAllMethod());
        return methodList;
    }
}
```

### 9.2 防止全表更新/删除插件

```java
@Bean
public MybatisPlusInterceptor mybatisPlusInterceptor() {
    MybatisPlusInterceptor interceptor = new MybatisPlusInterceptor();
    
    // 防止全表更新或删除
    interceptor.addInnerInterceptor(new BlockAttackInnerInterceptor());
    // 效果：没有 WHERE 条件的 UPDATE/DELETE 会抛出异常
    
    return interceptor;
}
```

### 9.3 SQL 性能规范插件

```java
interceptor.addInnerInterceptor(new IllegalSQLInnerInterceptor());
// 开发环境检测：全表扫描、索引使用、SQL 性能等问题会自动警告
```

---

## 10. Redis 缓存集成

### 10.1 Maven 依赖与配置

```xml
<dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-data-redis</artifactId>
</dependency>
<dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-cache</artifactId>
</dependency>
<!-- 连接池 -->
<dependency>
    <groupId>org.apache.commons</groupId>
    <artifactId>commons-pool2</artifactId>
</dependency>
```

```yaml
spring:
  data:
    redis:
      host: localhost
      port: 6379
      password: yourpassword
      database: 0
      lettuce:                 # Lettuce 连接池（默认客户端）
        pool:
          max-active: 16       # 最大连接数
          max-idle: 8          # 最大空闲连接
          min-idle: 4          # 最小空闲连接
          max-wait: 3000ms     # 等待超时
      timeout: 5000ms          # 连接超时
```

### 10.2 Redis 序列化配置

```java
@Configuration
@EnableCaching
public class RedisConfig {
    
    /**
     * 自定义 RedisTemplate 序列化（避免 JDK 序列化乱码问题）
     */
    @Bean
    public RedisTemplate<String, Object> redisTemplate(
            RedisConnectionFactory factory) {
        RedisTemplate<String, Object> template = new RedisTemplate<>();
        template.setConnectionFactory(factory);
        
        // JSON 序列化器
        Jackson2JsonRedisSerializer<Object> serializer = 
            new Jackson2JsonRedisSerializer<>(Object.class);
        ObjectMapper om = new ObjectMapper();
        om.setVisibility(PropertyAccessor.ALL, JsonAutoDetect.Visibility.ANY);
        om.activateDefaultTyping(
            om.getPolymorphicTypeValidator(), 
            ObjectMapper.DefaultTyping.NON_FINAL);
        serializer.setObjectMapper(om);
        
        // Key 使用 String 序列化
        StringRedisSerializer stringSerializer = new StringRedisSerializer();
        template.setKeySerializer(stringSerializer);
        template.setHashKeySerializer(stringSerializer);
        // Value 使用 JSON 序列化
        template.setValueSerializer(serializer);
        template.setHashValueSerializer(serializer);
        
        template.afterPropertiesSet();
        return template;
    }
    
    /**
     * 缓存管理器配置
     */
    @Bean
    public CacheManager cacheManager(RedisConnectionFactory factory) {
        RedisCacheConfiguration config = RedisCacheConfiguration.defaultCacheConfig()
            // 全局默认过期时间 30 分钟
            .entryTtl(Duration.ofMinutes(30))
            // 缓存 Key 前缀
            .prefixCacheNameWith("cache:")
            // 禁止缓存空值（防止缓存穿透可使用 true）
            .disableCachingNullValues()
            // Key 序列化
            .serializeKeysWith(
                RedisSerializationContext.SerializationPair
                    .fromSerializer(new StringRedisSerializer()))
            // Value 序列化
            .serializeValuesWith(
                RedisSerializationContext.SerializationPair
                    .fromSerializer(new Jackson2JsonRedisSerializer<>(Object.class)));
        
        return RedisCacheManager.builder(factory)
            .cacheDefaults(config)
            // 可为不同缓存名设置不同的过期时间
            .withCacheConfiguration("user",
                config.entryTtl(Duration.ofMinutes(10)))
            .withCacheConfiguration("product",
                config.entryTtl(Duration.ofHours(1)))
            .build();
    }
}
```

### 10.3 缓存注解使用

```java
@Service
@Slf4j
public class UserService extends ServiceImpl<UserMapper, User> {
    
    /**
     * @Cacheable: 先查缓存，缓存不存在再查数据库并存入缓存
     */
    @Cacheable(value = "user", key = "#id", unless = "#result == null")
    public User getUserById(Long id) {
        log.info("从数据库查询用户: {}", id);
        return baseMapper.selectById(id);
    }
    
    /**
     * @CachePut: 总是执行方法，并将结果更新到缓存
     */
    @CachePut(value = "user", key = "#user.id")
    public User updateUser(User user) {
        baseMapper.updateById(user);
        return user;
    }
    
    /**
     * @CacheEvict: 清除缓存
     */
    @CacheEvict(value = "user", key = "#id")
    public void deleteUser(Long id) {
        baseMapper.deleteById(id);
    }
    
    /**
     * @Caching: 组合多个缓存操作
     */
    @Caching(
        evict = {
            @CacheEvict(value = "user", key = "#user.id"),
            @CacheEvict(value = "userList", allEntries = true)
        }
    )
    public void updateWithCacheEvict(User user) {
        baseMapper.updateById(user);
    }
}
```

### 10.4 编程式缓存操作

```java
@Component
@RequiredArgsConstructor
public class RedisHelper {
    
    private final RedisTemplate<String, Object> redisTemplate;
    
    // 设置缓存（带过期时间）
    public void set(String key, Object value, Duration timeout) {
        redisTemplate.opsForValue().set(key, value, timeout);
    }
    
    // 获取缓存
    public <T> T get(String key) {
        return (T) redisTemplate.opsForValue().get(key);
    }
    
    // 删除缓存
    public Boolean delete(String key) {
        return redisTemplate.delete(key);
    }
    
    // 分布式锁
    public Boolean tryLock(String key, String value, Duration timeout) {
        return redisTemplate.opsForValue()
            .setIfAbsent(key, value, timeout);
    }
    
    // 释放锁（Lua 脚本保证原子性）
    public Boolean releaseLock(String key, String value) {
        String script = "if redis.call('get', KEYS[1]) == ARGV[1] " +
                       "then return redis.call('del', KEYS[1]) " +
                       "else return 0 end";
        DefaultRedisScript<Long> redisScript = new DefaultRedisScript<>();
        redisScript.setScriptText(script);
        redisScript.setResultType(Long.class);
        Long result = redisTemplate.execute(redisScript, Collections.singletonList(key), value);
        return result != null && result == 1;
    }
    
    // Pipeline 批量操作
    public void batchSet(Map<String, Object> dataMap) {
        redisTemplate.executePipelined((RedisCallback<Object>) connection -> {
            for (Map.Entry<String, Object> entry : dataMap.entrySet()) {
                connection.stringCommands().set(
                    entry.getKey().getBytes(),
                    JSON.toJSONBytes(entry.getValue())
                );
            }
            return null;
        });
    }
}
```

### 10.5 缓存三大问题解决方案

| 问题 | 原因 | 解决方案 |
|------|------|---------|
| **缓存穿透** | 查询不存在的数据，缓存不命中 | ① 缓存空值（短TTL）② 布隆过滤器 |
| **缓存击穿** | 热点 key 过期，大量请求直达 DB | ① 互斥锁 ② 逻辑过期（永不过期+异步刷新） |
| **缓存雪崩** | 大量 key 同时过期 | ① 过期时间加随机值 ② 多级缓存 ③ 熔断降级 |

```java
// 缓存穿透 - 缓存空值
@Cacheable(value = "user", key = "#id", unless = "#result == null")
public User getUserById(Long id) {
    User user = baseMapper.selectById(id);
    // unless 条件排除空值缓存
    return user;
}

// 缓存击穿 - 互斥锁
public User getUserByIdWithLock(Long id) {
    String cacheKey = "user:" + id;
    User user = redisHelper.get(cacheKey);
    if (user != null) return user;
    
    String lockKey = "lock:user:" + id;
    try {
        // 加锁失败则等待
        while (!redisHelper.tryLock(lockKey, "1", Duration.ofSeconds(10))) {
            Thread.sleep(100);
            user = redisHelper.get(cacheKey);
            if (user != null) return user;
        }
        // 双重检查
        user = redisHelper.get(cacheKey);
        if (user != null) return user;
        // 查数据库
        user = baseMapper.selectById(id);
        redisHelper.set(cacheKey, user, Duration.ofMinutes(30));
        return user;
    } finally {
        redisHelper.releaseLock(lockKey, "1");
    }
}

// 缓存雪崩 - 过期时间加随机值
private Duration randomExpiration() {
    long baseMinutes = 30;
    long randomMinutes = ThreadLocalRandom.current().nextLong(10);
    return Duration.ofMinutes(baseMinutes + randomMinutes);
}
```

---

## 11. 异步处理与线程池优化

### 11.1 `@EnableAsync` 启用异步

```java
@SpringBootApplication
@EnableAsync
public class DemoApplication {
    public static void main(String[] args) {
        SpringApplication.run(DemoApplication.class, args);
    }
}
```

### 11.2 线程池配置

```java
@Configuration
@EnableAsync
public class AsyncConfig implements AsyncConfigurer {
    
    @Override
    public Executor getAsyncExecutor() {
        ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();
        executor.setCorePoolSize(10);              // 核心线程数
        executor.setMaxPoolSize(50);               // 最大线程数
        executor.setQueueCapacity(200);            // 队列容量
        executor.setKeepAliveSeconds(60);          // 空闲线程存活时间
        executor.setThreadNamePrefix("async-");    // 线程名前缀
        // 拒绝策略：由调用线程执行
        executor.setRejectedExecutionHandler(
            new ThreadPoolExecutor.CallerRunsPolicy());
        // 等待任务完成后关闭
        executor.setWaitForTasksToCompleteOnShutdown(true);
        executor.setAwaitTerminationSeconds(30);
        executor.initialize();
        return executor;
    }
    
    @Override
    public AsyncUncaughtExceptionHandler getAsyncUncaughtExceptionHandler() {
        return (ex, method, params) -> {
            log.error("异步方法执行异常: {}, 方法: {}", ex.getMessage(), method.getName(), ex);
        };
    }
}
```

### 11.3 异步方法实现

```java
@Service
@Slf4j
public class EmailService {
    
    // 方式一: 默认线程池
    @Async
    public CompletableFuture<String> sendEmail(String to) {
        log.info("发送邮件给: {} [线程: {}]", to, Thread.currentThread().getName());
        // 模拟耗时操作
        try { Thread.sleep(2000); } catch (InterruptedException e) {}
        return CompletableFuture.completedFuture("邮件发送成功: " + to);
    }
    
    // 方式二: 指定线程池
    @Async("smsTaskExecutor")
    public void sendSms(String phone, String content) {
        log.info("发送短信到: {} [线程: {}]", phone, Thread.currentThread().getName());
    }
    
    // 方式三: CompletableFuture 组合
    @Async
    public CompletableFuture<UserReport> generateUserReport(Long userId) {
        User user = userService.getById(userId);
        List<Order> orders = orderService.getByUserId(userId);
        return CompletableFuture.completedFuture(
            new UserReport(user, orders));
    }
}
```

```java
@Bean("smsTaskExecutor")
public Executor smsTaskExecutor() {
    ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();
    executor.setCorePoolSize(5);
    executor.setMaxPoolSize(10);
    executor.setThreadNamePrefix("sms-");
    return executor;
}
```

### 11.4 CompletableFuture 组合调用

```java
@RestController
public class DashboardController {
    
    @Autowired
    private UserService userService;
    @Autowired
    private OrderService orderService;
    @Autowired
    private ProductService productService;
    
    @GetMapping("/dashboard")
    public DashboardVO getDashboard() {
        // 并行调用 3 个异步任务
        CompletableFuture<Long> userCount = 
            CompletableFuture.supplyAsync(() -> userService.count());
        CompletableFuture<Long> orderCount = 
            CompletableFuture.supplyAsync(() -> orderService.count());
        CompletableFuture<Long> productCount = 
            CompletableFuture.supplyAsync(() -> productService.count());
        
        // 等待所有任务完成
        CompletableFuture.allOf(userCount, orderCount, productCount).join();
        
        return DashboardVO.builder()
            .userCount(userCount.getNow(0L))
            .orderCount(orderCount.getNow(0L))
            .productCount(productCount.getNow(0L))
            .build();
    }
}
```

---

## 12. 可观测性 - Actuator + Prometheus + Grafana

### 12.1 引入依赖

```xml
<dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-actuator</artifactId>
</dependency>
<dependency>
    <groupId>io.micrometer</groupId>
    <artifactId>micrometer-registry-prometheus</artifactId>
</dependency>
```

### 12.2 配置

```yaml
management:
  server:
    port: 9001                          # 独立管理端口
  endpoints:
    web:
      exposure:
        include: health,info,metrics,prometheus,env,loggers
      base-path: /actuator
  endpoint:
    health:
      show-details: always
      show-components: always
  metrics:
    tags:
      application: ${spring.application.name}
```

### 12.3 自定义健康检查

```java
@Component
public class DatabaseHealthIndicator implements HealthIndicator {
    
    @Autowired
    private DataSource dataSource;
    
    @Override
    public Health health() {
        try (Connection conn = dataSource.getConnection()) {
            if (conn.isValid(3)) {
                return Health.up()
                    .withDetail("database", "MySQL")
                    .withDetail("status", "connected")
                    .build();
            }
        } catch (Exception e) {
            return Health.down(e)
                .withDetail("error", e.getMessage())
                .build();
        }
        return Health.unknown().build();
    }
}

@Component
public class RedisHealthIndicator implements HealthIndicator {
    
    @Autowired
    private RedisTemplate<String, String> redisTemplate;
    
    @Override
    public Health health() {
        try {
            String result = redisTemplate.execute(
                (RedisCallback<String>) connection -> {
                    return connection.ping();
                });
            if ("PONG".equals(result)) {
                return Health.up()
                    .withDetail("redis", "connected")
                    .build();
            }
        } catch (Exception e) {
            return Health.down(e).build();
        }
        return Health.unknown().build();
    }
}
```

### 12.4 自定义 Metrics

```java
@Component
public class BusinessMetrics {
    
    private final MeterRegistry meterRegistry;
    private final Counter orderCounter;
    private final Timer orderProcessTimer;
    
    public BusinessMetrics(MeterRegistry meterRegistry) {
        this.meterRegistry = meterRegistry;
        // 订单计数
        this.orderCounter = Counter.builder("orders.total")
            .description("订单总数")
            .tag("type", "create")
            .register(meterRegistry);
        // 订单处理耗时
        this.orderProcessTimer = Timer.builder("orders.process.time")
            .description("订单处理耗时")
            .register(meterRegistry);
    }
    
    public void recordOrderCreated() {
        orderCounter.increment();
    }
    
    public void recordOrderProcessTime(long millis) {
        orderProcessTimer.record(millis, TimeUnit.MILLISECONDS);
    }
}
```

### 12.5 Prometheus 与 Grafana

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'spring-boot-app'
    metrics_path: '/actuator/prometheus'
    static_configs:
      - targets: ['localhost:9001']
```

**关键监控指标：**

| 指标 | 说明 |
|------|------|
| `jvm_memory_used_bytes` | JVM 内存使用 |
| `jvm_gc_pause_seconds` | GC 暂停时间 |
| `http_server_requests_seconds` | HTTP 请求耗时 |
| `tomcat_threads_current` | Tomcat 当前线程数 |
| `hikaricp_connections_active` | 数据库活跃连接数 |
| `system_cpu_usage` | 系统 CPU 使用率 |

---

## 13. 分布式事务 Seata

### 13.1 概述与模式选择

Seata（Simple Extensible Autonomous Transaction Architecture）是阿里巴巴开源的分布式事务解决方案，支持三种模式：

| 模式 | 一致性 | 性能 | 适用场景 |
|------|--------|------|---------|
| **AT** | 最终一致 | 高 | 基于关系型数据库，大部分场景首选 |
| **TCC** | 强一致 | 中 | 对一致性要求极高，需实现 Try/Confirm/Cancel |
| **SAGA** | 最终一致 | 高 | 长事务、异构系统 |

### 13.2 Seata AT 模式原理

```
┌──────────────────────────────┐    ┌──────────────────────────────┐
│         TC (事务协调器)         │    │         TM (事务管理器)         │
│  Seata Server 负责全局事务管理  │    │  @GlobalTransactional 标注端   │
└──────────┬───────────────────┘    └──────────┬───────────────────┘
           │                                   │
    ┌──────┴────────────────────────┬──────────┴──────────┐
    │                               │                     │
┌───▼──────────┐          ┌────────▼──────┐    ┌─────────▼─────────┐
│  RM 资源管理器  │          │  RM 资源管理器  │    │  RM 资源管理器      │
│  订单服务      │          │  库存服务       │    │  账户服务          │
│  (undo_log)  │          │  (undo_log)   │    │  (undo_log)      │
└──────────────┘          └───────────────┘    └──────────────────┘
```

**AT 模式两阶段：**
1. **一阶段**：执行业务 SQL + 记录 undo_log（前镜像和后镜像）
2. **二阶段**：全局提交（删除 undo_log）或全局回滚（根据 undo_log 反向补偿）

### 13.3 Spring Boot 集成 Seata

**步骤 1：添加依赖**
```xml
<dependency>
    <groupId>com.alibaba.cloud</groupId>
    <artifactId>spring-cloud-starter-alibaba-seata</artifactId>
</dependency>
```

**步骤 2：配置**
```yaml
seata:
  enabled: true
  application-id: ${spring.application.name}
  tx-service-group: my_tx_group              # 事务服务组
  service:
    vgroup-mapping:
      my_tx_group: default                    # 映射到 Seata Server 集群
    grouplist:
      default: 127.0.0.1:8091                 # TC 地址
  data-source-proxy-mode: AT                  # 代理模式 AT
  config:
    type: nacos                               # 配置中心类型
    nacos:
      server-addr: 127.0.0.1:8848
      group: SEATA_GROUP
  registry:
    type: nacos                               # 注册中心类型
    nacos:
      server-addr: 127.0.0.1:8848
      group: SEATA_GROUP
```

**步骤 3：每个微服务数据库添加 undo_log 表**
```sql
CREATE TABLE `undo_log` (
    `id` BIGINT(20) NOT NULL AUTO_INCREMENT,
    `branch_id` BIGINT(20) NOT NULL,
    `xid` VARCHAR(100) NOT NULL,
    `context` VARCHAR(128) NOT NULL,
    `rollback_info` LONGBLOB NOT NULL,
    `log_status` INT(11) NOT NULL,
    `log_created` DATETIME NOT NULL,
    `log_modified` DATETIME NOT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `ux_undo_log` (`xid`, `branch_id`)
) ENGINE=InnoDB;
```

**步骤 4：使用全局事务**
```java
@Service
@Slf4j
public class OrderService {
    
    @Autowired
    private OrderMapper orderMapper;
    @Autowired
    private InventoryFeignClient inventoryClient;
    @Autowired
    private AccountFeignClient accountClient;
    
    @GlobalTransactional(name = "create-order-tx", rollbackFor = Exception.class)
    public void createOrder(OrderCreateDTO dto) {
        // 1. 创建订单（本地事务）
        Order order = buildOrder(dto);
        orderMapper.insert(order);
        
        // 2. 扣减库存（远程调用）
        inventoryClient.deductStock(dto.getProductId(), dto.getQuantity());
        
        // 3. 扣减余额（远程调用）
        accountClient.deductBalance(dto.getUserId(), dto.getTotalAmount());
        
        // 任何一步失败 → 全部回滚（Seata 自动补偿）
    }
}
```

---

## 14. Docker 容器化部署

### 14.1 多阶段构建 Dockerfile

```dockerfile
# ============ 阶段1: 构建应用 ============
FROM maven:3.9.6-eclipse-temurin-17 AS builder
WORKDIR /app
# 先拷贝 pom.xml 利用 Docker 缓存层
COPY pom.xml .
RUN mvn dependency:go-offline -B
# 再拷贝源码和构建
COPY src ./src
RUN mvn clean package -DskipTests

# ============ 阶段2: 运行应用 ============
FROM eclipse-temurin:17-jre-alpine AS runtime

# 安全加固：创建非 root 用户
RUN addgroup -S appgroup && adduser -S appuser -G appgroup

WORKDIR /app
# 从构建阶段拷贝 JAR
COPY --from=builder /app/target/*.jar app.jar

# 创建日志和数据目录
RUN mkdir -p /app/logs /app/data && \
    chown -R appuser:appgroup /app

# 切换到非 root 用户
USER appuser

# JVM 参数（支持容器环境）
ENV JAVA_OPTS="-XX:+UseContainerSupport \
               -XX:MaxRAMPercentage=75.0 \
               -XX:+UseZGC \
               -XX:+ZGenerational \
               -Djava.security.egd=file:/dev/./urandom"

EXPOSE 8080

# 健康检查
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://localhost:8080/actuator/health || exit 1

ENTRYPOINT ["sh", "-c", "java $JAVA_OPTS -jar app.jar"]
```

### 14.2 .dockerignore

```
.git
.gitignore
*.md
.DS_Store
.idea/
*.iml
target/
logs/
*.log
node_modules/
```

### 14.3 Docker Compose 编排

```yaml
version: '3.8'

services:
  # MySQL 数据库
  mysql:
    image: mysql:8.0
    container_name: app-mysql
    environment:
      MYSQL_ROOT_PASSWORD: root123
      MYSQL_DATABASE: app_db
      MYSQL_USER: app_user
      MYSQL_PASSWORD: app_password
    ports:
      - "3306:3306"
    volumes:
      - mysql_data:/var/lib/mysql
      - ./sql/init.sql:/docker-entrypoint-initdb.d/init.sql
    networks:
      - app-network
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost"]
      interval: 10s
      timeout: 5s
      retries: 5

  # Redis 缓存
  redis:
    image: redis:7-alpine
    container_name: app-redis
    command: redis-server --requirepass redis_password --appendonly yes
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    networks:
      - app-network
    healthcheck:
      test: ["CMD", "redis-cli", "--raw", "incr", "ping"]
      interval: 10s
      retries: 5

  # Spring Boot 应用
  app:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: app-server
    environment:
      SPRING_DATASOURCE_URL: jdbc:mysql://mysql:3306/app_db?serverTimezone=Asia/Shanghai
      SPRING_DATASOURCE_USERNAME: app_user
      SPRING_DATASOURCE_PASSWORD: app_password
      SPRING_DATA_REDIS_HOST: redis
      SPRING_DATA_REDIS_PASSWORD: redis_password
      JAVA_OPTS: "-Xms512m -Xmx1g"
    ports:
      - "8080:8080"
      - "9001:9001"     # Actuator 管理端口
    networks:
      - app-network
    depends_on:
      mysql:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped

volumes:
  mysql_data:
  redis_data:

networks:
  app-network:
    driver: bridge
```

### 14.4 构建与部署命令

```bash
# 构建镜像
docker build -t app-server:1.0.0 .

# 启动所有服务
docker compose up -d

# 查看日志
docker compose logs -f app

# 扩容实例
docker compose up -d --scale app=3

# 停止服务
docker compose down

# 推送到私有仓库
docker tag app-server:1.0.0 registry.example.com/app-server:1.0.0
docker push registry.example.com/app-server:1.0.0
```

---

## 15. 生产级最佳实践与性能优化

### 15.1 开发规范

**代码分层**：
```
Controller → Service(接口) → ServiceImpl(实现) → Mapper → DB
         ↘ DTO/VO 转换           ↗ Entity 映射
```

**命名规范**：
```java
// Controller
@GetMapping("/{id}")
public ApiResponse<UserVO> getById(@PathVariable Long id)

// Service
public interface UserService extends IService<User> { }
public class UserServiceImpl extends ServiceImpl<UserMapper, User> 
    implements UserService { }

// Mapper
@Mapper
public interface UserMapper extends BaseMapper<User> { }

// Entity：与数据库表一一对应
@Data
@TableName("user")
public class User { }

// DTO：前端→后端数据传输
@Data
public class UserCreateDTO {
    @NotBlank private String username;
    @Email private String email;
}

// VO：后端→前端视图对象
@Data
public class UserVO {
    private Long id;
    private String username;
    private String roleName;  // 关联查询转换
}
```

### 15.2 MyBatis-Plus 性能优化

**批量操作**：
```java
// ❌ 避免循环单条插入
for (User user : userList) {
    userMapper.insert(user);
}

// ✅ 使用批量插入
userService.saveBatch(userList, 1000);  // 每 1000 条一批

// ✅ 或自定义批量 SQL
@Insert("<script>INSERT INTO user(username, email) VALUES " +
        "<foreach collection='list' item='u' separator=','>" +
        "(#{u.username}, #{u.email})</foreach></script>")
int insertBatch(@Param("list") List<User> list);
```

**避免 N+1 查询**：
```java
// ❌ N+1 问题
List<User> users = userMapper.selectList(null);
for (User user : users) {
    List<Order> orders = orderMapper.selectByUserId(user.getId()); // N次查询
}

// ✅ 一次查询
List<Order> orders = orderMapper.selectByUserIds(users.stream()
    .map(User::getId).collect(Collectors.toList()));
Map<Long, List<Order>> orderMap = orders.stream()
    .collect(Collectors.groupingBy(Order::getUserId));
```

**分页查询注意事项**：
```java
// ❌ 先查总数再查数据
Long count = userMapper.selectCount(wrapper);      // 多一次查询
Page<User> page = new Page<>(1, 10);

// ✅ 分页插件自动处理（一次 SQL 同时返回 count + 数据）
Page<User> page = new Page<>(1, 10);
userMapper.selectPage(page, wrapper);
// page.getTotal()  // 总数
// page.getRecords() // 数据
```

### 15.3 Spring Boot 性能优化清单

**JVM 优化**：
```bash
java -jar app.jar \
  -XX:+UseContainerSupport \        # 适配容器内存限制
  -XX:MaxRAMPercentage=75.0 \       # JVM 最多使用 75% 内存
  -XX:+UseZGC \                     # JDK 17+ ZGC 低延迟垃圾回收
  -XX:+ZGenerational                # 分代 ZGC
```

**Tomcat 优化**：
```yaml
server:
  tomcat:
    max-connections: 10000           # 最大连接数
    accept-count: 200                # 等待队列长度
    threads:
      max: 200                       # 最大工作线程数
      min-spare: 20                  # 最小空闲线程数
    connection-timeout: 30000        # 连接超时（ms）
```

**数据库连接池优化**：
```yaml
spring:
  datasource:
    hikari:
      maximum-pool-size: 30          # 最大连接数
      minimum-idle: 10               # 最小空闲连接
      idle-timeout: 300000           # 空闲超时 5 分钟
      connection-timeout: 20000      # 连接获取超时
      max-lifetime: 1800000          # 连接最大存活 30 分钟
```

**接口响应优化**：
```java
// 添加 Gzip 压缩
server:
  compression:
    enabled: true
    mime-types: application/json,application/xml,text/html
    min-response-size: 1024          # 大于 1KB 才压缩
```

### 15.4 安全防护清单

| 防护项 | 措施 |
|--------|------|
| SQL 注入 | MyBatis-Plus 参数化查询自动防护 |
| XSS 攻击 | 输入过滤、输出编码 |
| CSRF | RESTful API 可禁用（JWT 无状态） |
| 密码安全 | BCryptPasswordEncoder 加密 |
| 敏感信息 | 配置文件加密、环境变量注入 |
| 接口限流 | Sentinel / Guava RateLimiter / Nginx |
| HTTPS | 生产环境强制启用 TLS 1.2+ |
| 依赖安全 | 定期 `mvn versions:display-dependency-updates` |

### 15.5 生产检查清单

```markdown
## 部署前检查

### 安全
- [ ] 关闭 /actuator/env、/actuator/heapdump 等敏感端点
- [ ] 所有密码使用环境变量或配置中心，不写在配置文件
- [ ] 生产环境禁用 DevTools
- [ ] 启用 CORS 白名单

### 性能
- [ ] 配置了合理的数据库连接池参数
- [ ] 关键查询添加了索引
- [ ] 热点数据配置了缓存
- [ ] 启用了 Gzip 压缩

### 高可用
- [ ] 配置了健康检查端点
- [ ] 配置了优雅关闭
- [ ] 数据库做了主从复制
- [ ] 设置了合理的超时时间

### 监��
- [ ] 集成了 Prometheus + Grafana
- [ ] 配置了日志收集（ELK / Loki）
- [ ] 配置了告警规则
- [ ] 请求日志记录了 traceId
```

### 15.6 优雅关闭

```yaml
server:
  shutdown: graceful                    # 优雅关闭
spring:
  lifecycle:
    timeout-per-shutdown-phase: 30s     # 关闭超时
```

---

## 结尾

本文档基于 Spring Boot 3.2+ 和 MyBatis-Plus 3.5.17 编写，涵盖了从高级特性到生产部署的全链路进阶内容。建议结合基础版一起阅读，形成完整的知识体系。

### 学习路径推荐

```
基础版 → 进阶版 → 实战项目
  │          │           │
  ├─ 环境搭建  ├─ 安全认证    ├─ 微服务架构
  ├─ CRUD操作 ├─ 多数据源    ├─ K8S 部署
  ├─ 分页查询  ├─ 缓存集成    ├─ CI/CD 流水线
  ├─ 代码生成  ├─ 分布式事务  └─ 性能调优
  └─ 事务管理  └─ Docker部署
```

---

*参考来源：Spring 官方文档（docs.spring.io）、MyBatis-Plus 官方文档（baomidou.com）、Seata 官方文档、CSDN、掘金、博客园、阿里云开发者社区等 20+ 篇技术文章*
