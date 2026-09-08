# 提示词模板示例库

这个目录包含各种实用的提示词模板示例。

## 文件说明

### template_library.py

包含完整的可复用模板库，分类如下：

- **翻译类模板**
  - TRANSLATOR - 专业翻译

- **编程类模板**
  - CODE_GENERATOR - 代码生成
  - CODE_REVIEWER - 代码审查
  - CODE_EXPLAINER - 代码解释
  - DEBUG_HELPER - 调试助手

- **内容创作类模板**
  - SUMMARIZER - 内容摘要
  - ARTICLE_WRITER - 文章写作
  - EMAIL_WRITER - 邮件撰写

- **教育类模板**
  - TUTOR - 教学辅导
  - QUIZ_GENERATOR - 测验生成

- **商务类模板**
  - PRODUCT_DESCRIPTION - 产品描述
  - MARKET_ANALYSIS - 市场分析

- **客户服务类模板**
  - CUSTOMER_SUPPORT - 客户服务
  - FAQ_RESPONDER - FAQ回答

- **数据分析类模板**
  - DATA_ANALYZER - 数据分析
  - REPORT_GENERATOR - 报告生成

## 使用方法

```python
from examples.template_library import TemplateLibrary

# 使用翻译模板
messages = TemplateLibrary.TRANSLATOR.format_messages(
    source_lang="英语",
    target_lang="中文",
    text="Hello World"
)

response = model.invoke(messages)
print(response.content)
```

## 测试模板库

```bash
python examples/template_library.py
```

## 自定义模板

你可以基于这些模板创建自己的变体：

```python
# 创建英译中专用模板
from examples.template_library import TemplateLibrary

en_to_zh = TemplateLibrary.TRANSLATOR.partial(
    source_lang="英语",
    target_lang="中文"
)

# 使用
messages = en_to_zh.format_messages(text="Hello")
```
