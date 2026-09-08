# 辅助函数
import re
import hashlib
from datetime import datetime

def generate_slug(title):
    """生成URL友好的slug"""
    # 转换为小写
    slug = title.lower()
    # 替换特殊字符
    slug = re.sub(r'[^\w\s-]', '', slug)
    # 替换空格为连字符
    slug = re.sub(r'[-\s]+', '-', slug)
    return slug

def calculate_hash(content):
    """计算内容哈希"""
    return hashlib.md5(content.encode()).hexdigest()

def format_datetime(dt):
    """格式化日期时间"""
    if dt is None:
        return None
    return dt.strftime('%Y-%m-%d %H:%M:%S')

def truncate_text(text, max_length=100):
    """截断文本"""
    if len(text) <= max_length:
        return text
    return text[:max_length] + '...'