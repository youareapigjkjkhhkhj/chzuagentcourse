# 实验8 PPO强化学习RLHF对齐医疗模型

> **类型**：✅必做实验 | **难度**：★★★★☆ | **时长**：4小时

## 实验目的
理解完整RLHF链路：SFT→奖励模型训练→PPO强化学习；对比DPO与PPO的差异。

## 实验原理
RLHF（Reinforcement Learning from Human Feedback）包含三个阶段：
1. **SFT阶段**：监督微调
2. **奖励模型训练**：训练RM打分
3. **PPO强化学习**：使用RM作为奖励信号优化策略

MedicalGPT提供了：
- 奖励模型训练脚本：`training/reward_modeling.py`
- PPO训练脚本：`training/ppo_training.py`（实际使用RLOO算法）

## 实验脚本与参数
- **奖励模型脚本**：`training/reward_modeling.py`
- **PPO脚本**：`training/ppo_training.py`
- **奖励模型启动脚本**：`scripts/run_rm.sh`
- **PPO启动脚本**：`scripts/run_ppo.sh`

## 实验内容

### 步骤1：准备奖励模型训练数据
```bash
# 查看奖励数据格式
head -n 3 data/reward/dpo_zh_500.jsonl
```

奖励数据格式（`data/reward/dpo_zh_500.jsonl`）：
```json
{"conversations": [{"from": "human", "value": "..."}], "chosen": "好回答", "rejected": "差回答"}
```

### 步骤2：训练医疗奖励模型
```bash
# run_rm_medical.sh - 医疗奖励模型训练脚本
CUDA_VISIBLE_DEVICES=0,1 python3 training/reward_modeling.py \
    --model_name_or_path Qwen/Qwen2.5-4B-Instruct \
    --train_file_dir ./data/reward \
    --validation_file_dir ./data/reward \
    --per_device_train_batch_size 4 \
    --gradient_accumulation_steps 8 \
    --per_device_eval_batch_size 4 \
    --do_train \
    --use_peft True \
    --seed 42 \
    --max_train_samples 500 \
    --max_eval_samples 10 \
    --num_train_epochs 1 \
    --learning_rate 2e-5 \
    --warmup_steps 5 \
    --weight_decay 0.001 \
    --logging_strategy steps \
    --logging_steps 10 \
    --eval_steps 50 \
    --eval_strategy steps \
    --save_steps 500 \
    --save_strategy steps \
    --save_total_limit 3 \
    --max_source_length 1024 \
    --max_target_length 256 \
    --output_dir outputs-rm-medical-qwen \
    --overwrite_output_dir \
    --ddp_timeout 30000 \
    --logging_first_step True \
    --target_modules all \
    --lora_rank 8 \
    --lora_alpha 16 \
    --lora_dropout 0.05 \
    --bf16 \
    --torch_dtype bfloat16 \
    --report_to tensorboard \
    --ddp_find_unused_parameters False \
    --remove_unused_columns False \
    --gradient_checkpointing True
```

> **注意**：奖励模型训练暂不支持torchrun多卡训练，使用`python3`直接启动。

### 步骤3：执行PPO强化学习训练
```bash
# run_ppo_medical.sh - PPO强化学习训练脚本
CUDA_VISIBLE_DEVICES=0,1 python3 training/ppo_training.py \
    --sft_model_path outputs-sft-lora-qwen \
    --reward_model_path outputs-rm-medical-qwen \
    --model_name_or_path Qwen/Qwen2.5-4B-Instruct \
    --dtype bfloat16 \
    --train_file_dir ./data/sft \
    --validation_file_dir ./data/sft \
    --max_source_length 1024 \
    --max_completion_length 1000 \
    --per_device_train_batch_size 1 \
    --gradient_accumulation_steps 4 \
    --gradient_checkpointing True \
    --do_train \
    --max_steps 3000 \
    --output_dir outputs-ppo-medical-qwen \
    --eval_strategy steps \
    --eval_steps 100 \
    --num_train_epochs 3 \
    --report_to tensorboard
```

> **关键参数说明**：
> - `--sft_model_path`：SFT微调后的模型路径
> - `--reward_model_path`：训练好的奖励模型路径
> - `--max_steps 3000`：PPO训练步数

### 步骤4：观察PPO训练过程
```python
# monitor_ppo_training.py - 监控PPO训练过程
from tensorboard.backend.event_processing.event_accumulator import EventAccumulator
import matplotlib.pyplot as plt

def plot_ppo_metrics(log_dir):
    ea = EventAccumulator(log_dir)
    ea.Reload()
    
    try:
        reward_events = ea.Scalars('ppo/rewards')
        kl_events = ea.Scalars('ppo/kl')
        
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
        
        ax1.plot([e.step for e in reward_events], [e.value for e in reward_events])
        ax1.set_xlabel('Steps')
        ax1.set_ylabel('Reward')
        ax1.set_title('PPO Reward')
        
        ax2.plot([e.step for e in kl_events], [e.value for e in kl_events])
        ax2.set_xlabel('Steps')
        ax2.set_ylabel('KL Divergence')
        ax2.set_title('PPO KL Divergence')
        
        plt.tight_layout()
        plt.savefig('ppo_metrics.png')
        print("PPO训练指标已保存: ppo_metrics.png")
    except Exception as e:
        print(f"获取指标失败: {e}")

if __name__ == "__main__":
    plot_ppo_metrics("outputs-ppo-medical-qwen/runs/")
```

### 步骤5：对比PPO与DPO输出的医疗回答效果
```python
# compare_ppo_dpo.py - 对比PPO与DPO
def compare_ppo_dpo():
    comparison = {
        "DPO": {
            "训练复杂度": "简单，无需奖励模型",
            "显存需求": "较低",
            "训练稳定性": "较稳定",
            "医疗问答效果": "良好",
        },
        "PPO": {
            "训练复杂度": "复杂，需要奖励模型",
            "显存需求": "较高（需同时加载策略模型和奖励模型）",
            "训练稳定性": "较不稳定，需要调参",
            "医疗问答效果": "理论上更好，但需要更多调参",
        }
    }
    
    print("PPO vs DPO对比:")
    print("-" * 60)
    for method, metrics in comparison.items():
        print(f"\n{method}:")
        for key, value in metrics.items():
            print(f"  {key}: {value}")

if __name__ == "__main__":
    compare_ppo_dpo()
```

## 实验产出
- 奖励模型：`outputs-rm-medical-qwen/`
- PPO强化学习后的模型：`outputs-ppo-medical-qwen/`
- PPO训练指标（reward、KL散度）
- PPO与DPO对比报告

## 思考题
1. 为什么PPO训练需要同时加载策略模型和奖励模型，而DPO不需要？
2. PPO训练中KL散度的作用是什么？
