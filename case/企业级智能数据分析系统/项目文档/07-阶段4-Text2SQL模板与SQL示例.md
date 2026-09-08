# 07 · 阶段 4 — Text2SQL 模板与 SQL 示例

> 本阶段目标：掌握 Text2SQL 的提示词模板体系（基础模板 + 12 种数据库方言模板）与 SQL 示例训练数据（`data_training`），理解「模板 + 示例 + 术语」如何共同校准 SQL 生成。

---

## 1. 目标

- 掌握 `apps/template/template.py` 的模板加载机制与 13 个 YAML 文件。
- 掌握 `apps/template/generate_sql/generator.py` 的 SQL 生成模板。
- 掌握 `apps/data_training/` SQL 示例训练（分页/启停/Excel 导入/embedding 检索）。
- 命令行实测：加载全部方言模板并检查关键字段。

## 2. 关键设计

### 2.1 模板体系（`apps/template/template.py`）

```text
backend/templates/
├── template.yaml             # 基础模板（通用提示词骨架）
└── sql_examples/             # 12 种方言 SQL 模板
    ├── PostgreSQL.yaml  MySQL.yaml  Oracle.yaml  ClickHouse.yaml
    ├── Doris.yaml  StarRocks.yaml  Hive.yaml  DM.yaml
    ├── Kingbase.yaml  AWS_Redshift.yaml  Microsoft_SQL_Server.yaml
    └── Elasticsearch.yaml
```

| 锚点 | 作用 |
|------|------|
| `template.py:9-12` | 路径常量（PROJECT_ROOT/templates 目录） |
| `template.py:16` | `_load_template_file`：读取 YAML |
| `template.py:27-29` | `get_base_template()`：基础模板 |
| `template.py:32-45` | `get_sql_template(db_type)`：按 DB 枚举映射方言文件名 |
| `template.py:48` | `get_all_sql_templates()`：全部模板 |

### 2.2 SQL 生成模板（`apps/template/generate_sql/generator.py`）

- `get_sql_template()`（`generator.py:7`）：SQL 生成提示词（输入：问题 + 表结构 + 示例 + 术语）。
- `get_sql_example_template(db_type)`（`generator.py:12`）：方言示例注入。

### 2.3 SQL 示例训练（`apps/data_training/`）

`router = APIRouter(prefix="/system/data-training")`（`data_training.py:26`）：

| 路由 | 锚点 | 作用 |
|------|------|------|
| `GET /page/{page}/{size}` | `data_training.py:29` | 分页列表 |
| `PUT ""` | `data_training.py:48` | 新增/更新 |
| `DELETE ""` | `data_training.py:60` | 删除 |
| `GET /{id}/enable/{enabled}` | `data_training.py:68` | 启停 |
| `GET /template` | `data_training.py:118` | 下载导入模板 |
| `POST /uploadExcel` | `data_training.py:165` | Excel 批量导入 |

数据表：`data_training_model.py`（DataTraining）—— 问题/SQL/库类型/表结构等字段，embedding 检索用于相似 SQL 示例召回（见阶段 5）。

## 3. 实操步骤

### 3.1 验证全部模板加载

```bash
cd 源码/backend
.venv/Scripts/python.exe -c "
from apps.template.template import get_all_sql_templates, get_sql_template, get_base_template
tpls = get_all_sql_templates()
print('方言模板数 =', len(tpls))
print('模板 key   =', sorted(tpls.keys()))
base = get_base_template()
print('基础模板字段 =', list(base.keys()))
pg = get_sql_template('pg')
print('pg 模板字段 =', list(pg.keys()))
"
```

实测输出：`方言模板数 = 13`（ck/dm/doris/es/excel/hive/kingbase/mysql/oracle/pg/redshift/sqlServer/starrocks）。

### 3.2 检查模板内容结构

```bash
.venv/Scripts/python.exe -c "
from apps.template.template import get_sql_template
t = get_sql_template('mysql')
s = str(t)[:200]
print('MySQL 模板预览:', s)
"
```

## 4. 可运行验证

| 验证项 | 命令 | 期望 |
|--------|------|------|
| 全量模板 | 3.1 | 13 个模板 key 正确 |
| 方言映射 | `get_sql_template('doris')` | 返回 Doris 模板 |
| 模板重载 | `template.py:60 reload_all_templates()` | 修改后热重载 |

**Checkpoint 达成标准**：模板加载与方言映射正确，为 SQL 生成提供提示词骨架。

## 5. 排错速查

| 现象 | 原因 | 处理 |
|------|------|------|
| 模板 key 与 DB 枚举不匹配 | 新增数据源未加模板 | 按 `sql_examples/*.yaml` 规范新增 |
| YAML 解析失败 | 模板格式错误 | 检查缩进与引号（`_load_template_file` 捕获异常） |
