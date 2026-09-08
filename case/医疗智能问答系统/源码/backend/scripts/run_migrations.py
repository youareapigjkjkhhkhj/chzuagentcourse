#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库迁移执行脚本

此脚本用于执行 SQL 迁移文件。

使用方法:
    python scripts/run_migrations.py [migration_file]

示例:
    python scripts/run_migrations.py migrations/001_setup_pgvector.sql
    python scripts/run_migrations.py  # 执行所有迁移
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


def read_sql_file(file_path):
    """读取 SQL 文件"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        print(f"✗ 读取文件失败: {e}")
        return None


def execute_sql(engine, sql_content, file_name):
    """执行 SQL 语句"""
    print(f"\n⏳ 执行迁移: {file_name}")
    
    try:
        with engine.connect() as conn:
            # 分割 SQL 语句（按分号分割，但忽略注释中的分号）
            statements = []
            current_statement = []
            
            for line in sql_content.split('\n'):
                # 跳过注释行
                stripped = line.strip()
                if stripped.startswith('--') or not stripped:
                    continue
                
                current_statement.append(line)
                
                # 如果行以分号结尾，表示一个语句结束
                if stripped.endswith(';'):
                    statements.append('\n'.join(current_statement))
                    current_statement = []
            
            # 执行每个语句
            for i, statement in enumerate(statements, 1):
                if statement.strip():
                    try:
                        conn.execute(text(statement))
                        print(f"  ✓ 语句 {i}/{len(statements)} 执行成功")
                    except Exception as e:
                        # 某些语句可能因为已存在而失败，这是正常的
                        if 'already exists' in str(e).lower():
                            print(f"  ⚠ 语句 {i}/{len(statements)} 已存在，跳过")
                        else:
                            print(f"  ✗ 语句 {i}/{len(statements)} 执行失败: {e}")
            
            conn.commit()
        
        print(f"✓ 迁移完成: {file_name}")
        return True
    except Exception as e:
        print(f"✗ 迁移失败: {e}")
        return False


def get_migration_files(migrations_dir):
    """获取所有迁移文件（按文件名排序）"""
    migration_files = []
    
    if migrations_dir.exists():
        for file_path in sorted(migrations_dir.glob('*.sql')):
            migration_files.append(file_path)
    
    return migration_files


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='执行数据库迁移')
    parser.add_argument('migration_file', nargs='?', help='要执行的迁移文件路径')
    parser.add_argument('--db', choices=['business', 'vector', 'both'], default='vector',
                       help='要迁移的数据库（默认: vector）')
    
    args = parser.parse_args()
    
    print("=" * 70)
    print("  数据库迁移工具")
    print("=" * 70)
    
    # 获取数据库连接
    business_db_url = os.getenv('DATABASE_URL')
    vector_db_url = os.getenv('VECTOR_DATABASE_URL')
    
    if not vector_db_url:
        print("\n✗ 错误: 未设置 VECTOR_DATABASE_URL 环境变量")
        return False
    
    try:
        # 确定要执行的迁移文件
        migrations_dir = project_root / 'migrations'
        
        if args.migration_file:
            # 执行指定的迁移文件
            migration_path = Path(args.migration_file)
            if not migration_path.is_absolute():
                migration_path = project_root / migration_path
            
            if not migration_path.exists():
                print(f"\n✗ 错误: 迁移文件不存在: {migration_path}")
                return False
            
            migration_files = [migration_path]
        else:
            # 执行所有迁移文件
            migration_files = get_migration_files(migrations_dir)
            
            if not migration_files:
                print(f"\n✗ 错误: 在 {migrations_dir} 中未找到迁移文件")
                return False
        
        print(f"\n找到 {len(migration_files)} 个迁移文件:")
        for f in migration_files:
            print(f"  - {f.name}")
        
        # 执行迁移
        success_count = 0
        
        for migration_file in migration_files:
            sql_content = read_sql_file(migration_file)
            if not sql_content:
                continue
            
            # 根据参数决定在哪个数据库上执行
            if args.db in ['vector', 'both']:
                engine = create_engine(vector_db_url)
                if execute_sql(engine, sql_content, migration_file.name):
                    success_count += 1
            
            if args.db in ['business', 'both'] and business_db_url:
                if business_db_url.startswith('postgresql'):
                    engine = create_engine(business_db_url)
                    if execute_sql(engine, sql_content, migration_file.name):
                        success_count += 1
        
        print("\n" + "=" * 70)
        print(f"✓ 迁移完成: {success_count}/{len(migration_files)} 个文件执行成功")
        print("=" * 70)
        
        return True
        
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
