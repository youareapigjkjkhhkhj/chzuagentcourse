#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PostgreSQL + pgvector 向量数据库初始化脚本

此脚本用于：
1. 启用 pgvector 扩展
2. 创建向量数据库表
3. 创建必要的索引

注意：业务数据（知识库、文档元数据等）存储在 SQLite 中
     只有向量数据存储在 PostgreSQL 中
"""

import os
import sys
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models.document_vector import init_vector_db, get_vector_session, DocumentVector, _vector_engine
from sqlalchemy import text


def init_pgvector_extension(session):
    """启用 pgvector 扩展"""
    print("正在启用 pgvector 扩展...")
    try:
        session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        session.commit()
        print("✓ pgvector 扩展已启用")
        return True
    except Exception as e:
        print(f"✗ 启用 pgvector 扩展失败: {e}")
        session.rollback()
        return False


def create_vector_index(session):
    """创建向量索引"""
    print("\n正在创建向量索引...")
    try:
        # 检查是否已存在向量数据
        vector_count = session.query(DocumentVector).count()
        
        if vector_count == 0:
            print("  提示: 当前没有向量数据，建议在添加数据后再创建索引")
            return True
        
        # 创建 HNSW 索引（适合大规模数据）
        print("  创建 HNSW 索引（这可能需要一些时间）...")
        session.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_document_vectors_embedding "
            "ON document_vectors USING hnsw (embedding vector_cosine_ops)"
        ))
        session.commit()
        print("✓ 向量索引创建成功")
        return True
    except Exception as e:
        print(f"✗ 创建向量索引失败: {e}")
        print("  提示: 可以稍后手动创建索引")
        session.rollback()
        return True  # 不阻止初始化流程


def verify_setup(session):
    """验证数据库设置"""
    print("\n正在验证数据库设置...")
    
    checks = []
    
    # 检查 pgvector 扩展
    try:
        result = session.execute(text(
            "SELECT * FROM pg_extension WHERE extname = 'vector'"
        ))
        if result.fetchone():
            checks.append(("pgvector 扩展", True))
        else:
            checks.append(("pgvector 扩展", False))
    except Exception as e:
        checks.append(("pgvector 扩展", False))
    
    # 检查表是否存在
    try:
        result = session.execute(text(
            "SELECT to_regclass('public.document_vectors')"
        ))
        if result.fetchone()[0]:
            checks.append(("表 document_vectors", True))
        else:
            checks.append(("表 document_vectors", False))
    except Exception as e:
        checks.append(("表 document_vectors", False))
    
    # 打印验证结果
    print("\n验证结果:")
    all_passed = True
    for check_name, passed in checks:
        status = "✓" if passed else "✗"
        print(f"  {status} {check_name}")
        if not passed:
            all_passed = False
    
    return all_passed


def main():
    """主函数"""
    print("=" * 60)
    print("PostgreSQL + pgvector 向量数据库初始化")
    print("=" * 60)
    
    # 检查向量数据库连接
    vector_db_url = os.getenv('VECTOR_DATABASE_URL', '')
    if not vector_db_url:
        print("\n✗ 错误: 未设置 VECTOR_DATABASE_URL 环境变量")
        print("  请在 .env 文件中添加:")
        print("  VECTOR_DATABASE_URL=postgresql://user:password@localhost:5432/vectors")
        return False
    
    if not vector_db_url.startswith('postgresql'):
        print("\n✗ 错误: VECTOR_DATABASE_URL 必须是 PostgreSQL 连接字符串")
        print(f"  当前值: {vector_db_url}")
        print("  示例: postgresql://user:password@localhost:5432/vectors")
        return False
    
    print(f"\n向量数据库连接: {vector_db_url.split('@')[1] if '@' in vector_db_url else vector_db_url}")
    print(f"业务数据库 (SQLite): {os.getenv('DATABASE_URL', 'sqlite:///app.db')}")
    
    try:
        # 初始化向量数据库
        print("\n正在初始化向量数据库...")
        init_vector_db(vector_db_url)
        print("✓ 向量数据库连接成功")
        
        # 获取会话
        session = get_vector_session()
        
        # 执行初始化步骤
        steps = [
            ("启用 pgvector 扩展", lambda: init_pgvector_extension(session)),
            ("创建向量索引", lambda: create_vector_index(session)),
        ]
        
        for step_name, step_func in steps:
            if not step_func():
                print(f"\n✗ 初始化失败于步骤: {step_name}")
                session.close()
                return False
        
        # 验证设置
        if verify_setup(session):
            print("\n" + "=" * 60)
            print("✓ 向量数据库初始化完成！")
            print("=" * 60)
            print("\n提示:")
            print("  - 业务数据（知识库、文档）存储在 SQLite 中")
            print("  - 向量数据存储在 PostgreSQL 中")
            print("  - 使用 python init_db.py 初始化 SQLite 数据库")
            session.close()
            return True
        else:
            print("\n" + "=" * 60)
            print("✗ 向量数据库初始化完成，但部分验证失败")
            print("=" * 60)
            session.close()
            return False
            
    except Exception as e:
        print(f"\n✗ 初始化失败: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
