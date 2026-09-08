#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
示例数据种子脚本

此脚本用于创建示例知识库和文档，方便测试和演示。

使用方法:
    python scripts/seed_data.py [--clean]

参数:
    --clean: 清除所有现有数据后再添加示例数据
"""

import os
import sys
import argparse
from pathlib import Path
from datetime import datetime
import uuid

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# 加载环境变量
load_dotenv()


def generate_id():
    """生成唯一ID"""
    return str(uuid.uuid4())


def clean_all_data(business_session, vector_session):
    """清除所有数据"""
    print("\n⏳ 清除现有数据...")
    
    try:
        from models.document_vector import DocumentVector
        from models.document import Document
        from models.knowledge_base import KnowledgeBase
        
        # 删除向量数据
        vector_session.query(DocumentVector).delete()
        vector_session.commit()
        print("  ✓ 已清除向量数据")
        
        # 删除文档
        business_session.query(Document).delete()
        business_session.commit()
        print("  ✓ 已清除文档数据")
        
        # 删除知识库
        business_session.query(KnowledgeBase).delete()
        business_session.commit()
        print("  ✓ 已清除知识库数据")
        
        return True
    except Exception as e:
        print(f"✗ 清除数据失败: {e}")
        return False


def create_sample_knowledge_bases(session):
    """创建示例知识库"""
    print("\n⏳ 创建示例知识库...")
    
    from models.knowledge_base import KnowledgeBase
    
    knowledge_bases = [
        {
            'id': generate_id(),
            'name': '医学知识库',
            'description': '包含常见疾病、症状、治疗方案等医学知识',
            'embedding_model': os.getenv('EMBEDDING_MODEL', 'text-embedding-3-small'),
            'status': 'active',
            'created_by': 'system'
        },
        {
            'id': generate_id(),
            'name': '药品信息库',
            'description': '药品说明书、用法用量、注意事项等信息',
            'embedding_model': os.getenv('EMBEDDING_MODEL', 'text-embedding-3-small'),
            'status': 'active',
            'created_by': 'system'
        },
        {
            'id': generate_id(),
            'name': '临床指南',
            'description': '各类疾病的临床诊疗指南和标准操作流程',
            'embedding_model': os.getenv('EMBEDDING_MODEL', 'text-embedding-3-small'),
            'status': 'active',
            'created_by': 'system'
        }
    ]
    
    created_kbs = []
    for kb_data in knowledge_bases:
        kb = KnowledgeBase(**kb_data)
        session.add(kb)
        created_kbs.append(kb)
        print(f"  ✓ 创建知识库: {kb.name}")
    
    session.commit()
    return created_kbs


def create_sample_documents(session, knowledge_bases):
    """创建示例文档"""
    print("\n⏳ 创建示例文档...")
    
    from models.document import Document
    
    # 医学知识库文档
    medical_docs = [
        {
            'title': '高血压诊疗指南',
            'content': '''高血压是最常见的慢性病之一，也是心脑血管病最主要的危险因素。

诊断标准：
- 收缩压 ≥140 mmHg 和/或舒张压 ≥90 mmHg
- 需要在非同日测量3次血压

分级：
1. 1级高血压（轻度）：收缩压140-159或舒张压90-99
2. 2级高血压（中度）：收缩压160-179或舒张压100-109
3. 3级高血压（重度）：收缩压≥180或舒张压≥110

治疗原则：
- 改善生活方式
- 药物治疗
- 定期监测血压
- 控制危险因素''',
            'category': '诊疗指南',
            'tags': '["高血压", "心血管", "慢性病"]',
            'status': 'draft'
        },
        {
            'title': '糖尿病管理要点',
            'content': '''糖尿病是一组以高血糖为特征的代谢性疾病。

诊断标准：
- 空腹血糖 ≥7.0 mmol/L
- 餐后2小时血糖 ≥11.1 mmol/L
- 糖化血红蛋白 ≥6.5%

分型：
1. 1型糖尿病：胰岛β细胞破坏
2. 2型糖尿病：胰岛素抵抗为主
3. 妊娠糖尿病
4. 其他特殊类型

管理目标：
- 血糖控制：空腹<7.0，餐后<10.0
- 糖化血红蛋白<7.0%
- 血压<130/80 mmHg
- 低密度脂蛋白<2.6 mmol/L''',
            'category': '疾病管理',
            'tags': '["糖尿病", "内分泌", "慢性病"]',
            'status': 'draft'
        }
    ]
    
    # 药品信息库文档
    drug_docs = [
        {
            'title': '阿司匹林肠溶片说明书',
            'content': '''【药品名称】
通用名称：阿司匹林肠溶片
英文名称：Aspirin Enteric-coated Tablets

【成份】本品主要成份为阿司匹林。

【适应症】
用于预防心脑血管疾病：
- 降低急性心肌梗死疑似患者的发病风险
- 预防心肌梗死复发
- 中风的二级预防
- 降低短暂性脑缺血发作及其继发脑卒中的风险

【用法用量】
口服。成人常用量：
- 预防心肌梗死：每日75-150mg
- 预防中风：每日50-325mg
- 餐后服用，整片吞服

【不良反应】
- 胃肠道反应：恶心、呕吐、胃痛
- 出血倾向
- 过敏反应

【禁忌】
- 对阿司匹林过敏者
- 活动性溃疡病
- 血友病或血小板减少症
- 孕妇及哺乳期妇女''',
            'category': '药品说明书',
            'tags': '["阿司匹林", "抗血小板", "心血管"]',
            'status': 'draft'
        }
    ]
    
    # 临床指南文档
    guideline_docs = [
        {
            'title': '急性心肌梗死诊疗规范',
            'content': '''急性心肌梗死（AMI）是冠状动脉急性、持续性缺血缺氧所引起的心肌坏死。

诊断要点：
1. 缺血性胸痛的临床病史
2. 心电图动态演变
3. 心肌损伤标志物升高
4. 影像学证据

紧急处理：
1. 立即吸氧
2. 建立静脉通路
3. 心电监护
4. 镇痛治疗
5. 抗血小板治疗
6. 抗凝治疗

再灌注治疗：
- 首选：急诊PCI（经皮冠状动脉介入治疗）
- 备选：溶栓治疗

时间窗：
- 发病12小时内应尽快进行再灌注治疗
- 黄金时间：发病后90分钟内''',
            'category': '急诊指南',
            'tags': '["心肌梗死", "急诊", "心血管"]',
            'status': 'draft'
        }
    ]
    
    # 创建文档
    doc_count = 0
    for kb in knowledge_bases:
        if '医学' in kb.name:
            docs = medical_docs
        elif '药品' in kb.name:
            docs = drug_docs
        elif '指南' in kb.name:
            docs = guideline_docs
        else:
            continue
        
        for doc_data in docs:
            doc = Document(
                id=generate_id(),
                kb_id=kb.id,
                title=doc_data['title'],
                content=doc_data['content'],
                category=doc_data['category'],
                tags=doc_data['tags'],
                status=doc_data['status'],
                author='system',
                views=0,
                chunk_count=0,
                vector_status='pending'
            )
            session.add(doc)
            doc_count += 1
            print(f"  ✓ 创建文档: {doc.title} (知识库: {kb.name})")
    
    session.commit()
    print(f"\n  共创建 {doc_count} 个文档")
    return doc_count


def print_summary(business_session):
    """打印数据摘要"""
    print("\n" + "=" * 70)
    print("  数据摘要")
    print("=" * 70)
    
    from models.knowledge_base import KnowledgeBase
    from models.document import Document
    
    kb_count = business_session.query(KnowledgeBase).count()
    doc_count = business_session.query(Document).count()
    
    print(f"\n知识库数量: {kb_count}")
    print(f"文档数量: {doc_count}")
    
    print("\n知识库列表:")
    kbs = business_session.query(KnowledgeBase).all()
    for kb in kbs:
        doc_count_in_kb = business_session.query(Document).filter_by(kb_id=kb.id).count()
        print(f"  - {kb.name}: {doc_count_in_kb} 个文档")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='创建示例数据')
    parser.add_argument('--clean', action='store_true', help='清除现有数据')
    args = parser.parse_args()
    
    print("=" * 70)
    print("  示例数据种子脚本")
    print("=" * 70)
    
    # 检查环境变量
    business_db_url = os.getenv('DATABASE_URL')
    vector_db_url = os.getenv('VECTOR_DATABASE_URL')
    
    if not business_db_url or not vector_db_url:
        print("\n✗ 错误: 未设置数据库连接环境变量")
        return False
    
    try:
        # 连接数据库
        business_engine = create_engine(business_db_url)
        vector_engine = create_engine(vector_db_url)
        
        BusinessSession = sessionmaker(bind=business_engine)
        VectorSession = sessionmaker(bind=vector_engine)
        
        business_session = BusinessSession()
        vector_session = VectorSession()
        
        # 清除数据（如果指定）
        if args.clean:
            if not clean_all_data(business_session, vector_session):
                return False
        
        # 创建示例数据
        knowledge_bases = create_sample_knowledge_bases(business_session)
        create_sample_documents(business_session, knowledge_bases)
        
        # 打印摘要
        print_summary(business_session)
        
        print("\n" + "=" * 70)
        print("✓ 示例数据创建完成")
        print("=" * 70)
        print("\n下一步:")
        print("  1. 启动应用: python run.py")
        print("  2. 访问前端界面查看示例数据")
        print("  3. 将文档状态改为'已发布'以触发向量化")
        
        business_session.close()
        vector_session.close()
        
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
