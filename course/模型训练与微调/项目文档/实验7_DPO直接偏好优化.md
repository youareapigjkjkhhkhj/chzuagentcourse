# 实验7 DPO直接偏好优化（医疗问答偏好对齐）

> **类型**：✅必做实验 | **难度**：★★★★☆ | **时长**：2.5小时

## 实验目的
掌握DPO偏好对齐，基于医疗偏好数据集，对SFT后的模型做人类偏好对齐，优化医疗回答风格。

## 实验原理
DPO（Direct Preference Optimization）通过偏好数据直接优化策略模型，无需训练奖励模型。MedicalGPT提供了`training/dpo_training.py`脚本。

## 实验脚本与参数
- **脚本路径**：`training/dpo_training.py`
- **启动脚本**：`scripts/run_dpo.sh`

## 实验内容

### 步骤1：构造医疗偏好数据集
```python
# create_medical_dpo_data.py - 构造医疗偏好数据集
import json

def create_medical_dpo_dataset(output_path):
    """构造医疗偏好数据集（好回答/差回答pair）"""
    dpo_samples = [
        {
            "conversations": [{"from": "human", "value": "感冒需要吃什么药？"}],
            "chosen": "感冒一般是由病毒引起的，通常不需要抗生素治疗。建议多休息、多喝水，可以服用对症药物如对乙酰氨基酚缓解发热和头痛。如果症状持续超过一周或出现高热、呼吸困难等症状，建议及时就医。注意：本回答仅供科普参考，不可替代专业医疗诊断。",
            "rejected": "感冒就吃阿莫西林和板蓝根，吃几天就好了。"
        },
        {
            "conversations": [{"from": "human", "value": "高血压患者能吃盐吗？"}],
            "chosen": "高血压患者需要控制盐的摄入量。建议每日食盐摄入量不超过5克（约一啤酒瓶盖的量）。应避免腌制食品、加工食品等高盐食物，多吃新鲜蔬果。同时建议定期监测血压，遵医嘱服药。注意：本回答仅供科普参考，具体饮食方案请咨询医生。",
            "rejected": "高血压不能吃盐，一点盐都不能吃。"
        },
        {
            "conversations": [{"from": "human", "value": "糖尿病能治好吗？"}],
            "chosen": "目前糖尿病还无法完全治愈，但可以通过规范治疗有效控制血糖。1型糖尿病需要终身注射胰岛素；2型糖尿病通过饮食控制、运动、口服药物或胰岛素治疗，可以将血糖控制在正常范围。关键是坚持治疗、定期复查、监测血糖。注意：本回答仅供科普参考，具体治疗方案请遵医嘱。",
            "rejected": "糖尿病吃点降糖药就行了，不用太在意。"
        },
        {
            "conversations": [{"from": "human", "value": "发烧了怎么办？"}],
            "chosen": "发烧是身体对抗感染的正常反应。体温在38.5°C以下时，可采用物理降温（温水擦浴、多饮水）。超过38.5°C可服用退烧药如对乙酰氨基酚或布洛芬。注意观察伴随症状，如持续高热、皮疹、意识模糊等应立即就医。发烧超过3天不退建议及时就诊。注意：本回答仅供科普参考。",
            "rejected": "发烧了吃退烧药就行，不用去医院。"
        },
        {
            "conversations": [{"from": "human", "value": "胃痛吃什么药？"}],
            "chosen": "胃痛的原因很多，常见包括胃炎、消化性溃疡、功能性消化不良等。建议先明确病因，可服用铝碳酸镁等胃黏膜保护剂缓解症状。避免辛辣刺激食物，规律饮食。如果胃痛反复发作或伴有呕血、黑便等症状，应立即就医检查。注意：本回答仅供科普参考，具体用药请遵医嘱。",
            "rejected": "胃痛吃止痛片就好了。"
        }
    ]
    
    with open(output_path, 'w', encoding='utf-8') as f:
        for sample in dpo_samples:
            f.write(json.dumps(sample, ensure_ascii=False) + '\n')
    
    print(f"医疗偏好数据集已创建: {output_path}")

if __name__ == "__main__":
    create_medical_dpo_dataset("data/reward/medical_dpo_zh.jsonl")
```

### 步骤2：使用DPO对SFT模型进行偏好对齐
```bash
# run_dpo_medical.sh - DPO偏好对齐启动脚本
CUDA_VISIBLE_DEVICES=0,1 python3 training/dpo_training.py \
    --model_name_or_path Qwen/Qwen2.5-4B-Instruct \
    --train_file_dir ./data/reward \
    --validation_file_dir ./data/reward \
    --per_device_train_batch_size 4 \
    --gradient_accumulation_steps 8 \
    --per_device_eval_batch_size 1 \
    --do_train \
    --do_eval \
    --use_peft True \
    --max_train_samples 500 \
    --max_eval_samples 10 \
    --max_steps 100 \
    --eval_steps 20 \
    --save_steps 50 \
    --max_source_length 1024 \
    --max_target_length 512 \
    --output_dir outputs-dpo-medical-qwen \
    --target_modules all \
    --lora_rank 8 \
    --lora_alpha 16 \
    --lora_dropout 0.05 \
    --torch_dtype bfloat16 \
    --bf16 True \
    --fp16 False \
    --report_to tensorboard \
    --remove_unused_columns False \
    --gradient_checkpointing True \
    --tool_format default \
    --cache_dir ./cache
```

> **关键参数说明**：
> - `--model_name_or_path`：可以是SFT微调后的模型路径
> - `--max_steps 100`：DPO训练步数
> - `--max_source_length 1024`：输入最大长度

### 步骤3：对比DPO对齐前后的医疗回答效果
```python
# compare_dpo_before_after.py - 对比DPO对齐前后效果
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel
import torch

def compare_dpo_effect(sft_model_path, dpo_model_path, test_queries):
    tokenizer = AutoTokenizer.from_pretrained(sft_model_path, trust_remote_code=True)
    
    sft_model = AutoModelForCausalLM.from_pretrained(
        sft_model_path, torch_dtype=torch.bfloat16, device_map="auto", trust_remote_code=True
    )
    sft_model = PeftModel.from_pretrained(sft_model, "outputs-sft-lora-qwen")
    
    dpo_model = AutoModelForCausalLM.from_pretrained(
        dpo_model_path, torch_dtype=torch.bfloat16, device_map="auto", trust_remote_code=True
    )
    dpo_model = PeftModel.from_pretrained(dpo_model, "outputs-dpo-medical-qwen")
    
    for query in test_queries:
        messages = [
            {"role": "system", "content": "你是一个专业的医疗科普助手。"},
            {"role": "user", "content": query}
        ]
        text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = tokenizer(text, return_tensors="pt").to(sft_model.device)
        
        with torch.no_grad():
            sft_output = sft_model.generate(**inputs, max_new_tokens=256, temperature=0.7)
            dpo_output = dpo_model.generate(**inputs, max_new_tokens=256, temperature=0.7)
        
        sft_response = tokenizer.decode(sft_output[0][inputs.input_ids.shape[1]:], skip_special_tokens=True)
        dpo_response = tokenizer.decode(dpo_output[0][inputs.input_ids.shape[1]:], skip_special_tokens=True)
        
        print(f"问题: {query}")
        print(f"SFT回答: {sft_response[:200]}...")
        print(f"DPO回答: {dpo_response[:200]}...")
        print("-" * 80)

if __name__ == "__main__":
    test_queries = [
        "感冒需要吃什么药？",
        "高血压患者日常饮食需要注意什么？"
    ]
    compare_dpo_effect(
        sft_model_path="Qwen/Qwen2.5-4B-Instruct",
        dpo_model_path="Qwen/Qwen2.5-4B-Instruct",
        test_queries=test_queries
    )
```

## 实验产出
- DPO对齐后的模型：`outputs-dpo-medical-qwen/`
- DPO对齐前后医疗回答对比结果

## 思考题
1. 为什么医疗场景优先DPO，而不是PPO？
2. DPO偏好数据的质量对对齐效果有什么影响？
