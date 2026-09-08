# 失明检测AI后端项目

基于Flask+MySQL的医疗AI诊断后端服务。

## 项目结构

```
backend/
├── app/                 # 应用核心代码
│   └── __init__.py     # 应用工厂
├── models/             # 数据模型
│   ├── __init__.py
│   ├── base.py         # 基础模型类
│   └── user.py         # 用户模型
├── routes/             # API路由
│   ├── __init__.py
│   ├── auth.py         # 认证相关路由
│   └── users.py        # 用户管理路由
├── utils/              # 工具函数
│   ├── __init__.py
│   ├── auth.py         # 认证工具
│   ├── response.py     # 统一响应格式
│   └── validators.py   # 数据验证器
├── .env                # 环境变量配置
├── .env.example        # 环境变量模板
├── requirements.txt    # Python依赖
├── run.py             # 应用启动文件
└── README.md          # 项目说明
```

## 环境配置

1. **安装依赖**：
   ```bash
   pip install -r requirements.txt
   ```

2. **环境变量配置**：
   复制 `.env.example` 到 `.env` 并修改配置：
   ```env
   # 数据库配置
   DATABASE_URL=mysql+pymysql://username:password@localhost:3306/blindness_db
   
   # JWT配置
   SECRET_KEY=your-super-secret-key-here
   JWT_EXPIRATION_HOURS=24
   
   # 应用配置
   FLASK_ENV=development
   DEBUG=True
   HOST=0.0.0.0
   PORT=5000
   ```

## 数据库设置

1. **创建MySQL数据库**：
   ```sql
   CREATE DATABASE blindness_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
   ```

2. **启动应用后会自动创建表结构**

## 启动应用

```bash
python run.py
```

应用将在 `http://localhost:5000` 启动

## API接口文档

### 认证接口

#### 用户注册
- **POST** `/api/auth/register`
- **Body**:
  ```json
  {
    "username": "testuser",
    "email": "test@example.com",
    "password": "password123",
    "full_name": "张三",
    "phone": "13800138000",
    "role": "user",
    "department": "眼科",
    "title": "主治医师",
    "hospital": "某某医院"
  }
  ```

#### 用户登录
- **POST** `/api/auth/login`
- **Body**:
  ```json
  {
    "username": "testuser",
    "password": "password123"
  }
  ```

#### 验证Token
- **GET** `/api/auth/verify`
- **Headers**: `Authorization: Bearer <token>`

#### 刷新Token
- **POST** `/api/auth/refresh`
- **Body**:
  ```json
  {
    "token": "current_token"
  }
  ```

### 用户管理接口

#### 获取用户列表
- **GET** `/api/users/`
- **Query Parameters**:
  - `page`: 页码 (默认1)
  - `per_page`: 每页数量 (默认10, 最大100)
  - `search`: 搜索关键词
  - `role`: 角色过滤
  - `is_active`: 状态过滤
- **Headers**: `Authorization: Bearer <token>`

#### 获取用户详情
- **GET** `/api/users/<user_id>`
- **Headers**: `Authorization: Bearer <token>`

#### 更新用户信息
- **PUT** `/api/users/<user_id>`
- **Headers**: `Authorization: Bearer <token>`
- **Body**: 要更新的字段

#### 删除用户（软删除）
- **DELETE** `/api/users/<user_id>`
- **Headers**: `Authorization: Bearer <admin_token>`

#### 获取当前用户信息
- **GET** `/api/users/profile`
- **Headers**: `Authorization: Bearer <token>`

#### 更新当前用户信息
- **PUT** `/api/users/profile`
- **Headers**: `Authorization: Bearer <token>`

#### 修改密码
- **POST** `/api/users/change-password`
- **Headers**: `Authorization: Bearer <token>`
- **Body**:
  ```json
  {
    "current_password": "old_password",
    "new_password": "new_password"
  }
  ```

## 响应格式

### 成功响应
```json
{
  "success": true,
  "message": "操作成功",
  "data": {
    // 具体数据
  }
}
```

### 错误响应
```json
{
  "success": false,
  "message": "错误信息",
  "error_code": "ERROR_CODE"
}
```

## 用户角色

- `user`: 普通用户
- `admin`: 管理员
- `doctor`: 医生

## 功能特性

1. **用户注册/登录**: 支持用户名或邮箱登录
2. **JWT认证**: 基于Token的无状态认证
3. **权限控制**: 角色-based访问控制
4. **数据验证**: 完整的前后端数据验证
5. **统一响应**: 标准化的API响应格式
6. **分页查询**: 支持用户列表分页和搜索
7. **软删除**: 用户删除采用软删除机制
8. **密码加密**: 使用bcrypt加密存储
9. **CORS支持**: 支持跨域请求

## 开发说明

1. 遵循RESTful API设计原则
2. 所有接口都有适当的错误处理
3. 使用SQLAlchemy ORM进行数据库操作
4. 支持MySQL数据库
5. 完整的日志记录和错误追踪

## 注意事项

1. 生产环境请修改默认SECRET_KEY
2. 定期更新依赖包版本
3. 数据库连接需要正确配置
4. 建议使用HTTPS进行生产部署