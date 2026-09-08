#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量训练脚本 - 自动训练多个模型
支持模型：resnet50, densenet121, efficientnet_b8, efficientnet_b3, efficientnet_b5, vit_base_patch16_224
"""

import os
import subprocess
import sys
import time
from datetime import datetime

# 定义要训练的模型列表
MODELS_TO_TRAIN = [
    
    {
        "name": "densenet121", 
        "pretrained_path": "./models/pre/densenet121-a639ec97.pth"
    },
    {
        "name": "efficientnet_b8",
        "pretrained_path": "./models/pre/tf_efficientnet_b8_ra-572d5dd9.pth"
    },
    {
        "name": "vit_base_patch16_224",
        "pretrained_path": "./models/pre/jx_vit_base_p16_224-80ecf9dd.pth"
    }
]

# 训练配置
TRAIN_SCRIPT = "train_res.py"
LOG_DIR = "./logs"
MAX_CONCURRENT_TRAININGS = 1  # 一次只训练一个模型，避免显存不足


def create_directories():
    """创建必要的目录"""
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs("./models", exist_ok=True)
    os.makedirs("./figures", exist_ok=True)


def check_pretrained_files():
    """检查预训练文件是否存在"""
    missing_files = []
    for model in MODELS_TO_TRAIN:
        if not os.path.exists(model["pretrained_path"]):
            missing_files.append(model["pretrained_path"])
    
    if missing_files:
        print("❌ 以下预训练文件不存在:")
        for file in missing_files:
            print(f"   - {file}")
        print("\n请确保预训练文件存在，或修改脚本中的路径。")
        return False
    return True


def train_single_model(model_info):
    """训练单个模型"""
    model_name = model_info["name"]
    pretrained_path = model_info["pretrained_path"]
    
    print(f"\n{'='*60}")
    print(f"������ 开始训练模型: {model_name}")
    print(f"������ 预训练权重: {pretrained_path}")
    print(f"⏰ 开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")
    
    # 创建模型特定的日志文件
    log_file = os.path.join(LOG_DIR, f"{model_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
    
    # 构建训练命令
    cmd = [
        sys.executable, TRAIN_SCRIPT,
        "--model", model_name,
        "--pretrained_path", pretrained_path
    ]
    
    print(f"������ 执行命令: {' '.join(cmd)}")
    print(f"������ 日志保存到: {log_file}")
    
    try:
        # 打开日志文件进行写入
        with open(log_file, 'w', encoding='utf-8') as f:
            f.write(f"模型训练开始: {model_name}\n")
            f.write(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"命令: {' '.join(cmd)}\n")
            f.write("="*60 + "\n\n")
            
            # 运行训练
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1
            )
            
            # 实时显示输出并写入日志
            for line in process.stdout:
                print(line.rstrip())
                f.write(line)
                f.flush()
            
            # 等待进程完成
            return_code = process.wait()
            
            f.write(f"\n训练结束，返回码: {return_code}\n")
            f.write(f"结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            
            if return_code == 0:
                print(f"✅ 模型 {model_name} 训练完成!")
                return True
            else:
                print(f"❌ 模型 {model_name} 训练失败 (返回码: {return_code})")
                return False
                
    except Exception as e:
        print(f"❌ 训练 {model_name} 时发生错误: {e}")
        return False


def main():
    """主函数"""
    print("������ APTOS 2019 批量训练脚本")
    print("="*60)
    
    # 创建必要目录
    create_directories()
    
    # 检查预训练文件
    if not check_pretrained_files():
        return
    
    print(f"������ 计划训练以下 {len(MODELS_TO_TRAIN)} 个模型:")
    for i, model in enumerate(MODELS_TO_TRAIN, 1):
        print(f"   {i}. {model['name']}")
    print(f"\n⏱️ 预计总训练时间: 约 {len(MODELS_TO_TRAIN) * 3:.1f} 小时")
    print(f"������ 日志目录: {LOG_DIR}")
    

    # 确认开始训练
    print("\n" + "="*60)
    confirm = input("������ 确认开始批量训练? (y/N): ").strip().lower()
    if confirm not in ['y', 'yes']:
        print("❌ 训练已取消")
        return
    
    print(f"\n������ 开始批量训练...")
    start_time = time.time()
    
    success_count = 0
    failed_models = []
    
    # 逐个训练模型
    for i, model in enumerate(MODELS_TO_TRAIN, 1):
        print(f"\n������ 进度: {i}/{len(MODELS_TO_TRAIN)} - 正在训练 {model['name']}")
        
        if train_single_model(model):
            success_count += 1
        else:
            failed_models.append(model['name'])
        
        # 如果不是最后一个模型，休息一下
        if i < len(MODELS_TO_TRAIN):
            print(f"\n⏸️  等待30秒后开始下一个模型...")
            time.sleep(30)
    
    # 训练完成总结
    end_time = time.time()
    total_time = (end_time - start_time) / 3600  # 转换为小时
    
    print(f"\n{'='*60}")
    print(f"������ 批量训练完成!")
    print(f"⏱️  总耗时: {total_time:.2f} 小时")
    print(f"✅ 成功: {success_count}/{len(MODELS_TO_TRAIN)} 个模型")
    
    if failed_models:
        print(f"❌ 失败: {len(failed_models)} 个模型")
        for model in failed_models:
            print(f"   - {model}")
    
    print(f"������ 所有日志保存在: {LOG_DIR}")
    print(f"������️  训练图表保存在: ./figures/")
    print(f"������ 模型权重保存在: ./models/")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()