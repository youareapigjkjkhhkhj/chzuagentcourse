# 实验5 QLoRA量化微调医疗大模型

> **类型**：✅必做实验 | **难度**：★★★☆☆ | **时长**：2小时

## 实验目的
掌握QLoRA 4bit量化微调原理，在量化基座上完成医疗领域微调。

## 实验原理
QLoRA（Quantized LoRA）在LoRA基础上引入4bit量化，进一步降低显存需求。MedicalGPT的SFT脚本通过`--load_in_4bit True --qlora True`启用QLoRA。

量化配置（`training/supervised_finetuning.py:727-733`）：
```python
if script_args.qlora:
    quantization_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_compute_dtype=torch_dtype,
        bnb_4bit_use_double_quant=True,
        bnb_4bit_quant_type="nf4"
    )
```

## 实验内容

### 步骤1：使用QLoRA进行SFT训练
```bash
# run_sft_qlora.sh - QLoRA微调启动脚本
CUDA_VISIBLE_DEVICES=0,1 torchrun --nproc_per_node 2 training/supervised_finetuning.py \
    --model_name_or_path Qwen/Qwen2.5-4B-Instruct \
    --train_file_dir ./data/sft \
    --validation_file_dir ./data/sft \
    --per_device_train_batch_size 4 \
    --per_device_eval_batch_size 2 \
    --do_train \
    --do_eval \
    --use_peft True \
    --load_in_4bit True \
    --qlora True \
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
    --gradient_accumulation_steps 4 \
    --preprocessing_num_workers 4 \
    --output_dir outputs-sft-qlora-qwen \
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
> - `--load_in_4bit True`：启用4bit量化加载
> - `--qlora True`：启用QLoRA（NF4量化 + double quantization）
> - `--per_device_train_batch_size 4`：量化后显存占用降低，可增大batch_size

### 步骤2：对比LoRA与QLoRA
```python
# compare_lora_qlora.py - 对比LoRA与QLoRA
def compare_lora_qlora():
    results = {
        "LoRA (16bit)": {
            "base_precision": "16bit",
            "gpu_memory_gb": "~16GB",
            "batch_size": 2,
            "training_speed": "基准",
        },
        "QLoRA (4bit)": {
            "base_precision": "4bit",
            "gpu_memory_gb": "~10GB",
            "batch_size": 4,
            "training_speed": "略慢(~10%)",
        }
    }
    
    print("LoRA vs QLoRA对比:")
    print("-" * 60)
    for method, metrics in results.items():
        print(f"\n{method}:")
        for key, value in metrics.items():
            print(f"  {key}: {value}")

if __name__ == "__main__":
    compare_lora_qlora()
```

### 步骤3：推理加载QLoRA权重测试医疗问答
```python
# test_qlora_medical.py - 测试QLoRA微调后的医疗问答
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from peft import PeftModel
import torch

def test_qlora_model(base_model_path, lora_path, test_queries):
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
        bnb_4bit_quant_type="nf4"
    )
    
    tokenizer = AutoTokenizer.from_pretrained(base_model_path, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        base_model_path, quantization_config=bnb_config, device_map="auto", trust_remote_code=True
    )
    model = PeftModel.from_pretrained(model, lora_path)
    
    for query in test_queries:
        messages = [
            {"role": "system", "content": "你是一个专业的医疗科普助手。"},
            {"role": "user", "content": query}
        ]
        text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = tokenizer(text, return_tensors="pt").to(model.device)
        
        with torch.no_grad():
            outputs = model.generate(**inputs, max_new_tokens=512, temperature=0.7)
        
        response = tokenizer.decode(outputs[0][inputs.input_ids.shape[1]:], skip_special_tokens=True)
        print(f"问题: {query}")
        print(f"回答: {response}")
        print("-" * 80)

if __name__ == "__main__":
    test_queries = [
        "感冒需要吃什么药？",
        "高血压患者日常饮食需要注意什么？",
        "糖尿病的早期症状有哪些？"
    ]
    test_qlora_model(
        base_model_path="Qwen/Qwen2.5-4B-Instruct",
        lora_path="outputs-sft-qlora-qwen",
        test_queries=test_queries
    )
```

## 实验产出
- QLoRA微调后的LoRA权重：`outputs-sft-qlora-qwen/`
- LoRA与QLoRA对比报告
- 医疗问答测试结果

## 思考题
1. QLoRA 4bit量化微调会损失一部分精度，在医疗场景下，会带来哪些风险？
2. NF4量化相比普通4bit量化有什么优势？
