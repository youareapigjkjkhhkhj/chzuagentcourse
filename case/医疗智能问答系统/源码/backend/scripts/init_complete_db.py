#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
完整数据库初始化脚本

此脚本用于初始化整个系统的数据库，包括：
1. PostgreSQL + pgvector 向量数据库
2. 业务数据库（知识库、文档等）
3. 创建所有必要的索引
4. 初始化默认设置数据

使用方法:
    python scripts/init_complete_db.py
"""

import os
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
from sqlalchemy import text, create_engine, inspect
from sqlalchemy.orm import sessionmaker

# 加载环境变量
load_dotenv()


def print_header(title):
    """打印标题"""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def print_step(step_name, status="进行中"):
    """打印步骤"""
    symbols = {
        "进行中": "⏳",
        "成功": "✓",
        "失败": "✗",
        "警告": "⚠"
    }
    symbol = symbols.get(status, "•")
    print(f"{symbol} {step_name}")


def check_environment():
    """检查环境变量配置"""
    print_header("检查环境配置")
    
    required_vars = {
        'DATABASE_URL': '业务数据库连接',
        'VECTOR_DATABASE_URL': '向量数据库连接',
        'EMBEDDING_MODEL': '嵌入模型',
        'EMBEDDING_DIMENSION': '向量维度',
        'EMBEDDINGS_API_URL': '嵌入API地址'
    }
    
    missing_vars = []
    for var, desc in required_vars.items():
        value = os.getenv(var)
        if value:
            # 隐藏敏感信息
            if 'URL' in var and '@' in value:
                display_value = value.split('@')[1] if '@' in value else value
            else:
                display_value = value
            print_step(f"{desc}: {display_value}", "成功")
        else:
            print_step(f"{desc}: 未设置", "失败")
            missing_vars.append(var)
    
    if missing_vars:
        print(f"\n✗ 缺少必要的环境变量: {', '.join(missing_vars)}")
        print("  请在 .env 文件中配置这些变量")
        return False
    
    return True


def init_pgvector_extension(engine):
    """启用 pgvector 扩展"""
    print_step("启用 pgvector 扩展", "进行中")
    
    try:
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()
        print_step("启用 pgvector 扩展", "成功")
        return True
    except Exception as e:
        print_step(f"启用 pgvector 扩展失败: {e}", "失败")
        return False


def create_business_tables(engine):
    """创建业务数据表"""
    print_step("创建业务数据表", "进行中")
    
    try:
        # 导入所有模型以确保表被创建
        from models import db
        from models.knowledge_base import KnowledgeBase
        from models.document import Document
        from models.settings import KnowledgeBaseSettings
        
        # 创建所有表
        db.metadata.create_all(bind=engine)
        
        print_step("创建业务数据表", "成功")
        return True
    except Exception as e:
        print_step(f"创建业务数据表失败: {e}", "失败")
        return False


def create_vector_tables(engine):
    """创建向量数据表"""
    print_step("创建向量数据表", "进行中")
    
    try:
        from models.document_vector import DocumentVector, Base
        
        # 创建向量表
        Base.metadata.create_all(bind=engine)
        
        print_step("创建向量数据表", "成功")
        return True
    except Exception as e:
        print_step(f"创建向量数据表失败: {e}", "失败")
        return False


def create_indexes(engine, db_type='postgresql'):
    """创建数据库索引"""
    print_step(f"创建 {db_type} 索引", "进行中")
    
    try:
        with engine.connect() as conn:
            if db_type == 'postgresql':
                # PostgreSQL 特定索引
                indexes = [
                    # 知识库索引
                    "CREATE INDEX IF NOT EXISTS idx_knowledge_bases_status ON knowledge_bases(status)",
                    "CREATE INDEX IF NOT EXISTS idx_knowledge_bases_created_at ON knowledge_bases(created_at DESC)",
                    
                    # 文档索引
                    "CREATE INDEX IF NOT EXISTS idx_documents_kb_status ON documents(kb_id, status)",
                    "CREATE INDEX IF NOT EXISTS idx_documents_vector_status ON documents(kb_id, vector_status)",
                    "CREATE INDEX IF NOT EXISTS idx_documents_created_at ON documents(created_at DESC)",
                    "CREATE INDEX IF NOT EXISTS idx_documents_category ON documents(category)",
                    
                    # 全文搜索索引
                    "CREATE INDEX IF NOT EXISTS idx_documents_content_fts ON documents USING gin(to_tsvector('english', content))",
                    "CREATE INDEX IF NOT EXISTS idx_documents_title_fts ON documents USING gin(to_tsvector('english', title))",
                ]
                
                for index_sql in indexes:
                    try:
                        conn.execute(text(index_sql))
                    except Exception as e:
                        print(f"    警告: 索引创建失败 - {str(e)[:50]}")
                
                conn.commit()
            
        print_step(f"创建 {db_type} 索引", "成功")
        return True
    except Exception as e:
        print_step(f"创建索引失败: {e}", "警告")
        return True  # 索引创建失败不应阻止初始化


def create_vector_index(engine):
    """创建向量索引（HNSW）"""
    print_step("创建向量索引", "进行中")
    
    try:
        with engine.connect() as conn:
            # 检查是否已有数据
            result = conn.execute(text("SELECT COUNT(*) FROM document_vectors"))
            count = result.scalar()
            
            if count == 0:
                print_step("向量表为空，跳过索引创建（建议在添加数据后创建）", "警告")
                return True
            
            # 创建 HNSW 索引
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_document_vectors_embedding "
                "ON document_vectors USING hnsw (embedding vector_cosine_ops)"
            ))
            conn.commit()
            
        print_step("创建向量索引", "成功")
        return True
    except Exception as e:
        print_step(f"创建向量索引失败: {e}", "警告")
        print("    提示: 可以稍后使用 scripts/create_vector_index.py 创建索引")
        return True  # 不阻止初始化流程


def init_default_settings(engine):
    """初始化默认设置"""
    print_step("初始化默认设置", "进行中")
    
    try:
        from models.settings import KnowledgeBaseSettings
        from models import db
        
        Session = sessionmaker(bind=engine)
        session = Session()
        
        # 检查是否已存在设置
        existing = session.query(KnowledgeBaseSettings).filter_by(id='default').first()
        
        if not existing:
            # 创建默认设置
            default_settings = KnowledgeBaseSettings(
                id='default',
                vector_db_type='pgvector',
                embedding_model=os.getenv('EMBEDDING_MODEL', 'text-embedding-3-small'),
                embedding_dimension=int(os.getenv('EMBEDDING_DIMENSION', '1536')),
                chunk_size=1000,
                chunk_overlap=200,
                similarity_threshold=0.7,
                max_search_results=10
            )
            session.add(default_settings)
            session.commit()
            print_step("初始化默认设置", "成功")
        else:
            print_step("默认设置已存在，跳过", "警告")
        
        session.close()
        return True
    except Exception as e:
        print_step(f"初始化默认设置失败: {e}", "失败")
        return False


def verify_setup(business_engine, vector_engine):
    """验证数据库设置"""
    print_header("验证数据库设置")
    
    checks = []
    
    # 检查业务数据库表
    try:
        inspector = inspect(business_engine)
        tables = inspector.get_table_names()
        required_tables = ['knowledge_bases', 'documents', 'knowledge_base_settings']
        
        for table in required_tables:
            if table in tables:
                checks.append((f"业务表 {table}", True))
            else:
                checks.append((f"业务表 {table}", False))
    except Exception as e:
        checks.append(("业务数据库连接", False))
    
    # 检查向量数据库
    try:
        with vector_engine.connect() as conn:
            # 检查 pgvector 扩展
            result = conn.execute(text(
                "SELECT * FROM pg_extension WHERE extname = 'vector'"
            ))
            if result.fetchone():
                checks.append(("pgvector 扩展", True))
            else:
                checks.append(("pgvector 扩展", False))
            
            # 检查向量表
            result = conn.execute(text(
                "SELECT to_regclass('public.document_vectors')"
            ))
            if result.fetchone()[0]:
                checks.append(("向量表 document_vectors", True))
            else:
                checks.append(("向量表 document_vectors", False))
    except Exception as e:
        checks.append(("向量数据库连接", False))
    
    # 打印验证结果
    all_passed = True
    for check_name, passed in checks:
        print_step(check_name, "成功" if passed else "失败")
        if not passed:
            all_passed = False
    
    return all_passed


def main():
    """主函数"""
    print_header("知识库管理系统 - 数据库初始化")
    
    # 1. 检查环境配置
    if not check_environment():
        return False
    
    # 2. 初始化业务数据库
    print_header("初始化业务数据库")
    
    business_db_url = os.getenv('DATABASE_URL')
    try:
        business_engine = create_engine(business_db_url)
        
        if not create_business_tables(business_engine):
            return False
        
        # 如果是 PostgreSQL，创建索引
        if business_db_url.startswith('postgresql'):
            create_indexes(business_engine, 'postgresql')
        
        if not init_default_settings(business_engine):
            return False
            
    except Exception as e:
        print_step(f"业务数据库初始化失败: {e}", "失败")
        return False
    
    # 3. 初始化向量数据库
    print_header("初始化向量数据库 (PostgreSQL + pgvector)")
    
    vector_db_url = os.getenv('VECTOR_DATABASE_URL')
    try:
        vector_engine = create_engine(vector_db_url)
        
        if not init_pgvector_extension(vector_engine):
            return False
        
        if not create_vector_tables(vector_engine):
            return False
        
        create_indexes(vector_engine, 'postgresql')
        create_vector_index(vector_engine)
        
    except Exception as e:
        print_step(f"向量数据库初始化失败: {e}", "失败")
        return False
    
    # 4. 验证设置
    if verify_setup(business_engine, vector_engine):
        print_header("✓ 数据库初始化完成")
        print("\n下一步:")
        print("  1. 启动应用: python run.py")
        print("  2. 访问前端界面创建知识库")
        print("  3. 上传文档并进行向量化")
        print("\n提示:")
        print("  - 使用 scripts/create_vector_index.py 在有数据后创建向量索引")
        print("  - 使用 scripts/seed_data.py 添加示例数据")
        return True
    else:
        print_header("✗ 数据库初始化完成，但部分验证失败")
        print("\n请检查上述失败项并手动修复")
        return False


if __name__ == '__main__':
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n✗ 初始化被用户中断")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n✗ 初始化过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
