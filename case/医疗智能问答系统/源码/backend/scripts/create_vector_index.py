#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
向量索引创建脚本

此脚本用于在向量表中创建 HNSW 索引以加速向量搜索。
建议在向量表有一定数据量后再创建索引。

使用方法:
    python scripts/create_vector_index.py [--force] [--index-type hnsw|ivfflat]

参数:
    --force: 强制重建索引（删除旧索引）
    --index-type: 索引类型，默认为 hnsw
"""

import os
import sys
import argparse
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# 加载环境变量
load_dotenv()


def get_vector_count(engine):
    """获取向量数量"""
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT COUNT(*) FROM document_vectors"))
            return result.scalar()
    except Exception as e:
        print(f"✗ 获取向量数量失败: {e}")
        return 0


def drop_existing_index(engine, index_name):
    """删除现有索引"""
    try:
        with engine.connect() as conn:
            conn.execute(text(f"DROP INDEX IF EXISTS {index_name}"))
            conn.commit()
        print(f"✓ 已删除旧索引: {index_name}")
        return True
    except Exception as e:
        print(f"✗ 删除索引失败: {e}")
        return False


def create_hnsw_index(engine, m=16, ef_construction=64):
    """
    创建 HNSW 索引
    
    参数:
        m: HNSW 参数，控制图的连接度（默认16，范围2-100）
        ef_construction: 构建时的搜索深度（默认64，范围4-1000）
    
    HNSW 索引特点:
    - 查询速度快
    - 适合大规模数据（>10万条）
    - 构建时间较长
    - 内存占用较多
    """
    print(f"\n⏳ 创建 HNSW 索引 (m={m}, ef_construction={ef_construction})...")
    print("   这可能需要几分钟时间，请耐心等待...")
    
    try:
        with engine.connect() as conn:
            # 创建 HNSW 索引
            conn.execute(text(
                f"CREATE INDEX idx_document_vectors_embedding "
                f"ON document_vectors "
                f"USING hnsw (embedding vector_cosine_ops) "
                f"WITH (m = {m}, ef_construction = {ef_construction})"
            ))
            conn.commit()
        
        print("✓ HNSW 索引创建成功")
        return True
    except Exception as e:
        print(f"✗ HNSW 索引创建失败: {e}")
        return False


def create_ivfflat_index(engine, lists=100):
    """
    创建 IVFFlat 索引
    
    参数:
        lists: 聚类数量（建议为行数的平方根）
    
    IVFFlat 索引特点:
    - 构建速度快
    - 适合中等规模数据（1万-10万条）
    - 查询速度中等
    - 内存占用少
    """
    print(f"\n⏳ 创建 IVFFlat 索引 (lists={lists})...")
    
    try:
        with engine.connect() as conn:
            # 创建 IVFFlat 索引
            conn.execute(text(
                f"CREATE INDEX idx_document_vectors_embedding "
                f"ON document_vectors "
                f"USING ivfflat (embedding vector_cosine_ops) "
                f"WITH (lists = {lists})"
            ))
            conn.commit()
        
        print("✓ IVFFlat 索引创建成功")
        return True
    except Exception as e:
        print(f"✗ IVFFlat 索引创建失败: {e}")
        return False


def check_index_exists(engine):
    """检查索引是否存在"""
    try:
        with engine.connect() as conn:
            result = conn.execute(text(
                "SELECT indexname FROM pg_indexes "
                "WHERE tablename = 'document_vectors' "
                "AND indexname = 'idx_document_vectors_embedding'"
            ))
            return result.fetchone() is not None
    except Exception as e:
        print(f"✗ 检查索引失败: {e}")
        return False


def get_index_info(engine):
    """获取索引信息"""
    try:
        with engine.connect() as conn:
            result = conn.execute(text(
                "SELECT "
                "    indexname, "
                "    pg_size_pretty(pg_relation_size(indexname::regclass)) as size, "
                "    indexdef "
                "FROM pg_indexes "
                "WHERE tablename = 'document_vectors' "
                "AND indexname = 'idx_document_vectors_embedding'"
            ))
            row = result.fetchone()
            if row:
                return {
                    'name': row[0],
                    'size': row[1],
                    'definition': row[2]
                }
        return None
    except Exception as e:
        print(f"✗ 获取索引信息失败: {e}")
        return None


def recommend_index_params(vector_count):
    """根据数据量推荐索引参数"""
    if vector_count < 10000:
        return {
            'type': 'none',
            'reason': '数据量较小，可以不创建索引'
        }
    elif vector_count < 100000:
        lists = max(int(vector_count ** 0.5), 10)
        return {
            'type': 'ivfflat',
            'lists': lists,
            'reason': '数据量中等，推荐使用 IVFFlat 索引'
        }
    else:
        return {
            'type': 'hnsw',
            'm': 16,
            'ef_construction': 64,
            'reason': '数据量较大，推荐使用 HNSW 索引'
        }


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='创建向量索引')
    parser.add_argument('--force', action='store_true', help='强制重建索引')
    parser.add_argument('--index-type', choices=['hnsw', 'ivfflat'], default='hnsw', help='索引类型')
    parser.add_argument('--m', type=int, default=16, help='HNSW m 参数 (2-100)')
    parser.add_argument('--ef-construction', type=int, default=64, help='HNSW ef_construction 参数 (4-1000)')
    parser.add_argument('--lists', type=int, help='IVFFlat lists 参数（默认为行数的平方根）')
    
    args = parser.parse_args()
    
    print("=" * 70)
    print("  向量索引创建工具")
    print("=" * 70)
    
    # 检查环境变量
    vector_db_url = os.getenv('VECTOR_DATABASE_URL')
    if not vector_db_url:
        print("\n✗ 错误: 未设置 VECTOR_DATABASE_URL 环境变量")
        return False
    
    print(f"\n向量数据库: {vector_db_url.split('@')[1] if '@' in vector_db_url else vector_db_url}")
    
    try:
        # 连接数据库
        engine = create_engine(vector_db_url)
        
        # 获取向量数量
        vector_count = get_vector_count(engine)
        print(f"\n当前向量数量: {vector_count:,}")
        
        if vector_count == 0:
            print("\n⚠ 警告: 向量表为空")
            print("  建议先添加数据再创建索引")
            return False
        
        # 推荐索引参数
        recommendation = recommend_index_params(vector_count)
        print(f"\n推荐: {recommendation['reason']}")
        if recommendation['type'] != 'none':
            print(f"  索引类型: {recommendation['type'].upper()}")
            if recommendation['type'] == 'hnsw':
                print(f"  参数: m={recommendation['m']}, ef_construction={recommendation['ef_construction']}")
            elif recommendation['type'] == 'ivfflat':
                print(f"  参数: lists={recommendation['lists']}")
        
        # 检查现有索引
        if check_index_exists(engine):
            print("\n⚠ 索引已存在")
            
            # 显示索引信息
            index_info = get_index_info(engine)
            if index_info:
                print(f"  名称: {index_info['name']}")
                print(f"  大小: {index_info['size']}")
                print(f"  定义: {index_info['definition']}")
            
            if not args.force:
                print("\n使用 --force 参数强制重建索引")
                return True
            
            # 删除旧索引
            print("\n⏳ 删除旧索引...")
            if not drop_existing_index(engine, 'idx_document_vectors_embedding'):
                return False
        
        # 创建索引
        if args.index_type == 'hnsw':
            success = create_hnsw_index(engine, args.m, args.ef_construction)
        else:
            lists = args.lists if args.lists else max(int(vector_count ** 0.5), 10)
            success = create_ivfflat_index(engine, lists)
        
        if success:
            # 显示新索引信息
            print("\n索引信息:")
            index_info = get_index_info(engine)
            if index_info:
                print(f"  名称: {index_info['name']}")
                print(f"  大小: {index_info['size']}")
            
            print("\n" + "=" * 70)
            print("✓ 索引创建完成")
            print("=" * 70)
            print("\n提示:")
            print("  - 索引会自动用于向量搜索")
            print("  - 定期运行 VACUUM ANALYZE 以优化性能")
            print("  - 如果数据量大幅增加，考虑重建索引")
            return True
        else:
            return False
            
    except Exception as e:
        print(f"\n✗ 错误: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n✗ 操作被用户中断")
        sys.exit(1)
