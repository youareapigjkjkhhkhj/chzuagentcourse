#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
检查环境变量
"""

import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

print("环境变量检查:")
print(f"EMBEDDING_MODEL: {os.getenv('EMBEDDING_MODEL')}")
print(f"EMBEDDINGS_API_URL: {os.getenv('EMBEDDINGS_API_URL')}")
print(f"EMBEDDING_DIMENSION: {os.getenv('EMBEDDING_DIMENSION')}")

# 测试VectorManager初始化
from utils.vector_manager import VectorManager

vector_manager = VectorManager()
print("\nVectorManager配置:")
print(f"嵌入模型: {vector_manager.embedding_model}")
print(f"嵌入API URL: {vector_manager.embeddings_api_url}")
print(f"向量维度: {vector_manager.dimension}")