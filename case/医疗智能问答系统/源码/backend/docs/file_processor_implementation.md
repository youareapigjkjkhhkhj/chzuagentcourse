# FileProcessor 实现文档

## 概述

FileProcessor 是一个文件处理工具类，用于从多种格式的文件中提取文本内容，支持知识库系统的文档导入功能。

## 支持的文件格式

- **TXT**: 纯文本文件（支持多种编码：UTF-8, GBK, GB2312, Latin-1）
- **Markdown (.md)**: Markdown 格式文件
- **PDF**: PDF 文档（使用 pypdf 库）
- **DOCX**: Microsoft Word 文档（使用 python-docx 库）
- **XLSX**: Microsoft Excel 表格（使用 openpyxl 库）
- **PPTX**: Microsoft PowerPoint 演示文稿（使用 python-pptx 库）

## 主要功能

### 1. 文件验证

```python
processor = FileProcessor()
is_valid, error_msg = processor.validate_file(file_path, file_type)
```

验证文件是否：
- 存在
- 大小在限制范围内（最大 50MB）
- 格式受支持

### 2. 文本提取

```python
content = processor.extract_text(file_path, file_type)
```

从文件中提取文本内容，自动根据文件类型调用相应的处理方法。

### 3. ZIP 批量处理

```python
results = processor.process_zip(zip_path, kb_id)
```

处理 ZIP 压缩包，批量提取其中的文件内容。返回结果列表，包含每个文件的处理状态。

### 4. 文件信息获取

```python
info = processor.get_file_info(file_path)
```

获取文件的基本信息（文件名、类型、大小、是否支持）。

## 使用示例

### 基本使用

```python
from utils.file_processor import FileProcessor

processor = FileProcessor()

# 提取 PDF 文件内容
try:
    content = processor.extract_text('/path/to/document.pdf', 'pdf')
    print(content)
except Exception as e:
    print(f"处理失败: {str(e)}")
```

### ZIP 批量处理

```python
# 处理 ZIP 文件
results = processor.process_zip('/path/to/documents.zip', 'kb_123')

for result in results:
    if result['success']:
        print(f"✓ {result['file_name']}: {len(result['content'])} 字符")
    else:
        print(f"✗ {result['file_name']}: {result['error']}")
```

## 特殊处理说明

### TXT 文件编码处理

TXT 文件会尝试多种编码方式读取：
1. UTF-8
2. GBK
3. GB2312
4. Latin-1

如果所有编码都失败，会使用 UTF-8 并忽略错误字符。

### PDF 文件处理

- 按页提取文本
- 每页添加页码标记
- 跳过无法提取的页面并记录警告

### DOCX 文件处理

- 提取段落文本
- 提取表格内容（使用 `|` 分隔单元格）

### XLSX 文件处理

- 遍历所有工作表
- 添加工作表名称标记
- 使用 `|` 分隔单元格内容

### PPTX 文件处理

- 按幻灯片提取文本
- 添加幻灯片编号
- 提取形状中的文本
- 提取表格内容

## 错误处理

所有处理方法都会抛出异常，调用方需要捕获并处理：

```python
try:
    content = processor.extract_text(file_path, file_type)
except ValueError as e:
    # 文件验证失败
    print(f"验证错误: {str(e)}")
except Exception as e:
    # 文件解析失败
    print(f"解析错误: {str(e)}")
```

## 依赖库

```
pypdf>=4.0.0
python-docx>=1.0.0
python-pptx>=0.6.23
openpyxl>=3.1.5
```

## 测试

运行测试脚本验证功能：

```bash
cd backend
python test_file_processor.py
```

## 限制和注意事项

1. **文件大小限制**: 单个文件最大 50MB
2. **编码问题**: TXT 文件可能存在编码识别不准确的情况
3. **PDF 限制**: 扫描版 PDF 无法提取文本（需要 OCR）
4. **临时文件**: ZIP 处理会创建临时目录，处理完成后自动清理
5. **性能考虑**: 大文件处理可能耗时较长，建议异步处理

## 未来改进

- [ ] 支持更多文件格式（如 RTF、ODT 等）
- [ ] 添加 OCR 支持处理扫描版 PDF
- [ ] 优化大文件处理性能
- [ ] 添加进度回调支持
- [ ] 支持文件内容预览（前 N 个字符）
