# 实验4 LoRA高效微调医疗大模型

> **类型**：✅必做实验 | **难度**：★★★☆☆ | **时长**：2小时

## 实验目的
掌握LoRA适配器微调原理，对比全参微调，使用LoRA对Qwen2‑4B做医疗SFT。

## 实验原理
LoRA（Low-Rank Adaptation）通过在权重矩阵旁添加低秩分解矩阵来实现参数高效微调。MedicalGPT的SFT脚本默认启用LoRA（`--use_peft True`）。

LoRA关键参数（`training/supervised_finetuning.py:194-201`）：
```python
use_peft: bool = field(default=True, metadata={"help": "Whether to use peft"})
target_modules: Optional[str] = field(default="all")
lora_rank: Optional[int] = field(default=8)
lora_dropout: Optional[float] = field(default=0.05)
lora_alpha: Optional[float] = field(default=32.0)
```

## 实验脚本与参数
- **脚本路径**：`training/supervised_finetuning.py`
- **启动脚本**：`scripts/run_sft.sh`

## 实验内容

### 步骤1：使用LoRA进行SFT训练
```bash
# run_sft_lora.sh - LoRA微调启动脚本
CUDA_VISIBLE_DEVICES=0,1 torchrun --nproc_per_node 2 training/supervised_finetuning.py \
    --model_name_or_path Qwen/Qwen2.5-4B-Instruct \
    --train_file_dir ./data/sft \
    --validation_file_dir ./data/sft \
    --per_device_train_batch_size 2 \
    --per_device_eval_batch_size 1 \
    --do_train \
    --do_eval \
    --use_peft True \
    --max_train_samples 1000 \
    --max_eval_samples 10 \
    --model_max_length 512 \
    --num_train_epochs 1 \
    --learning_rate 2e-5 \
    --warmup_steps 5 \
    --weight_decay 0.05 \
    --logging_strategy steps \
    --logging_steps 10 \
    --eval_steps 50 \
    --eval_strategy steps \
    --save_steps 500 \
    --save_strategy steps \
    --save_total_limit 3 \
    --gradient_accumulation_steps 8 \
    --preprocessing_num_workers 4 \
    --output_dir outputs-sft-lora-qwen \
    --ddp_timeout 30000 \
    --logging_first_step True \
    --target_modules all \
    --lora_rank 8 \
    --lora_alpha 16 \
    --lora_dropout 0.05 \
    --torch_dtype bfloat16 \
    --bf16 \
    --report_to tensorboard \
    --ddp_find_unused_parameters False \
    --gradient_checkpointing True \
    --tool_format default \
    --cache_dir ./cache \
    --flash_attn True
```

> **关键参数说明**：
> - `--use_peft True`：启用LoRA微调
> - `--target_modules all`：对所有线性层应用LoRA
> - `--lora_rank 8`：LoRA低秩矩阵的秩
> - `--lora_alpha 16`：LoRA缩放因子

### 步骤2：查看LoRA参数量
```python
# check_lora_params.py - 查看LoRA可训练参数
from peft import PeftModel
from transformers import AutoModelForCausalLM
import torch

def count_lora_params(model_path, peft_path):
    model = AutoModelForCausalLM.from_pretrained(
        model_path, torch_dtype=torch.bfloat16, trust_remote_code=True
    )
    model = PeftModel.from_pretrained(model, peft_path)
    
    trainable_params = 0
    all_params = 0
    for _, param in model.named_parameters():
        all_params += param.numel()
        if param.requires_grad:
            trainable_params += param.numel()
    
    print(f"可训练参数: {trainable_params:,}")
    print(f"总参数: {all_params:,}")
    print(f"可训练比例: {100 * trainable_params / all_params:.2f}%")

if __name__ == "__main__":
    count_lora_params("Qwen/Qwen2.5-4B-Instruct", "outputs-sft-lora-qwen")
```

### 步骤3：保存LoRA权重并推理测试
```python
# merge_lora.py - 合并LoRA权重到基座模型
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

def merge_lora_weights(base_model_path, lora_path, output_path):
    model = AutoModelForCausalLM.from_pretrained(
        base_model_path, torch_dtype=torch.bfloat16, trust_remote_code=True
    )
    model = PeftModel.from_pretrained(model, lora_path)
    model = model.merge_and_unload()
    
    model.save_pretrained(output_path)
    tokenizer = AutoTokenizer.from_pretrained(base_model_path, trust_remote_code=True)
    tokenizer.save_pretrained(output_path)
    print(f"LoRA权重已合并并保存到: {output_path}")

if __name__ == "__main__":
    merge_lora_weights(
        base_model_path="Qwen/Qwen2.5-4B-Instruct",
        lora_path="outputs-sft-lora-qwen",
        output_path="outputs-merged-lora-qwen"
    )
```

### 步骤4：对比全参微调与LoRA
```python
# compare_methods.py - 对比全参微调与LoRA
def compare_training_methods():
    results = {
        "full_ft": {
            "trainable_params": "4,000,000,000",
            "trainable_ratio": "100%",
            "gpu_memory_gb": "~38GB",
            "training_speed": "较慢",
        },
        "lora": {
            "trainable_params": "20,000,000",
            "trainable_ratio": "0.5%",
            "gpu_memory_gb": "~16GB",
            "training_speed": "较快",
        }
    }
    
    print("全参微调 vs LoRA对比:")
    print("-" * 60)
    for method, metrics in results.items():
        print(f"\n{method}:")
        for key, value in metrics.items():
            print(f"  {key}: {value}")

if __name__ == "__main__":
    compare_training_methods()
```

## 实验产出
- LoRA权重：`outputs-sft-lora-qwen/`
- 合并后的完整模型：`outputs-merged-lora-qwen/`
- 参数量对比结果

## 思考题
1. LoRA的rank参数大小对模型效果和显存占用有什么影响？
2. LoRA为什么能实现与全参微调接近的效果？
