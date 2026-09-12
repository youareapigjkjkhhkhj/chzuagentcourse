#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Flask应用入口文件
"""

import os
import sys

# Windows 控制台默认使用 GBK，无法输出 emoji（如 ✅ ❌），会导致 UnicodeEncodeError 直接崩溃。
# 必须在 create_app() 之前执行：模型管理器是在导入 routes 时实例化的。
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from dotenv import load_dotenv
from app import create_app

# 加载环境变量
load_dotenv()

# 创建应用实例
app = create_app()

if __name__ == '__main__':
    # 配置Flask JSON编码
    app.config['JSON_AS_ASCII'] = False
    app.config['JSONIFY_PRETTYPRINT_REGULAR'] = True
    
    app.run(
        host=os.getenv('HOST', '0.0.0.0'),
        port=int(os.getenv('PORT', 5000)),
        debug=os.getenv('DEBUG', 'False').lower() == 'true'
    )