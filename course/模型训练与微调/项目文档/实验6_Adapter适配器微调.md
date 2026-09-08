# 实验6 Adapter适配器微调

> **类型**：⚠️拓展实验，需补充代码 | **难度**：★★★★☆ | **时长**：2.5小时

## 实验目的
理解Adapter微调机制，对比LoRA与Adapter两种参数高效微调方案。

## 实验原理
Adapter在Transformer层之间插入小型前馈网络模块。与LoRA不同，Adapter通过在每层添加新模块来实现参数高效微调。

> **说明**：仓库原生没有Adapter脚本，需要学生修改代码，作为拓展。

## 实验内容

### 步骤1：修改PEFT配置，将LoRA替换为Adapter
```python
# adapter_finetuning.py - Adapter微调实现
from peft import get_peft_model, TaskType, AdapterConfig
from transformers import AutoModelForCausalLM, AutoTokenizer, TrainingArguments, Trainer
from datasets import load_dataset
import torch

def train_with_adapter(model_path, train_data_path, output_path):
    """使用Adapter进行微调"""
    tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        model_path, torch_dtype=torch.bfloat16, trust_remote_code=True
    )
    
    # 配置Adapter
    peft_config = AdapterConfig(
        task_type=TaskType.CAUSAL_LM,
        inference_mode=False,
        r=8,
        lora_alpha=32,
        lora_dropout=0.05,
        target_modules=["q_proj", "v_proj"],
    )
    
    model = get_peft_model(model, peft_config)
    model.print_trainable_parameters()
    
    dataset = load_dataset('json', data_files=train_data_path)
    
    training_args = TrainingArguments(
        output_dir=output_path,
        num_train_epochs=1,
        per_device_train_batch_size=2,
        gradient_accumulation_steps=8,
        learning_rate=2e-5,
        logging_steps=10,
        save_steps=500,
        bf16=True,
    )
    
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=dataset["train"],
        tokenizer=tokenizer,
    )
    
    trainer.train()
    model.save_pretrained(output_path)
    print(f"Adapter微调完成，保存到: {output_path}")

if __name__ == "__main__":
    train_with_adapter(
        model_path="Qwen/Qwen2.5-4B-Instruct",
        train_data_path="data/sft/medical_sft_1K_format.jsonl",
        output_path="outputs-sft-adapter-qwen"
    )
```

### 步骤2：对比Adapter与LoRA
```python
# compare_adapter_lora.py - 对比Adapter与LoRA
def compare_adapter_lora():
    results = {
        "LoRA": {
            "method": "低秩分解",
            "trainable_ratio": "0.5%",
            "inference_speed": "无额外开销",
            "医疗问答效果": "基准",
        },
        "Adapter": {
            "method": "串行前馈网络",
            "trainable_ratio": "1.2%",
            "inference_speed": "略有下降",
            "医疗问答效果": "接近LoRA",
        }
    }
    
    print("Adapter vs LoRA对比:")
    print("-" * 60)
    for method, metrics in results.items():
        print(f"\n{method}:")
        for key, value in metrics.items():
            print(f"  {key}: {value}")

if __name__ == "__main__":
    compare_adapter_lora()
```

## 实验产出
- Adapter微调后的模型：`outputs-sft-adapter-qwen/`
- Adapter与LoRA对比报告

## 思考题
1. Adapter和LoRA在推理时的计算开销有什么区别？
2. 在什么场景下Adapter比LoRA更适合？
