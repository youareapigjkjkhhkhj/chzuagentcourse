# MedicalGPT: 医疗领域大模型训练框架

> 基于ChatGPT训练流程的医疗大模型训练框架，支持预训练、有监督微调、RLHF、DPO等全流程训练。

## 项目介绍

本项目实现了医疗领域大模型的完整训练流程，包括：

- **增量预训练（PT）**：在海量医疗领域文档数据上二次预训练GPT模型，注入领域知识
- **有监督微调（SFT）**：构造指令微调数据集，在预训练模型基础上做指令精调
- **奖励模型训练（RM）**：构造人类偏好排序数据集，训练奖励模型
- **强化学习训练（RL）**：使用奖励模型训练SFT模型，优化生成质量
- **直接偏好优化（DPO）**：无需强化学习，直接优化语言模型以符合人类偏好

## 项目结构

```
MedicalGPT/
├── training/                # 核心训练脚本
│   ├── template.py                         # 对话模板定义
│   ├── tool_utils.py                       # Agent工具调用格式化工具
│   ├── pretraining.py                      # Stage 1: 增量预训练(PT)
│   ├── supervised_finetuning.py            # Stage 2: 有监督微调(SFT)
│   ├── opd_training.py                     # Stage 2.5: 独立OPD蒸馏
│   ├── reward_modeling.py                  # Stage 3: 奖励模型(RM)
│   ├── ppo_training.py                     # Stage 3: 强化学习(PPO/RLOO)
│   ├── dpo_training.py                     # Stage 3: 直接偏好优化(DPO)
│   ├── orpo_training.py                    # Stage 3: ORPO
│   └── grpo_training.py                    # Stage 3: GRPO
│
├── scripts/                 # 一键运行脚本 + DeepSpeed配置
│   ├── run_pt.sh / run_sft.sh / run_dpo.sh / ...
│   └── zero1.json / zero2.json / zero3.json
│
├── demo/                    # 推理、部署、应用示例
│   ├── inference.py / gradio_demo.py / fastapi_server_demo.py
│   ├── openai_api.py / chatpdf.py
│   └── inference_multigpu_demo.py
│
├── tools/                   # 模型合并、量化、数据处理工具
│   ├── merge_peft_adapter.py / merge_tokenizers.py
│   ├── model_quant.py / eval_quantize.py
│   └── convert_dataset.py / validate_jsonl.py
│
├── notebooks/               # Jupyter Notebook教程
│   ├── run_training_dpo_pipeline.ipynb
│   └── run_training_ppo_pipeline.ipynb
│
├── data/                    # 训练数据
│   ├── sft/                               # SFT数据（含普通问答和Tool Call）
│   ├── reward/                            # DPO/RM偏好数据
│   └── pretrain/                          # 预训练数据
│
├── docs/                    # 文档
└── tests/                   # 测试
```

## 训练流程

| 阶段 | 说明 | Python脚本 | Shell脚本 |
|:-----|:-----|:-----------|:----------|
| Continue Pretraining | 增量预训练 | `training/pretraining.py` | `scripts/run_pt.sh` |
| Supervised Fine-tuning | 有监督微调 | `training/supervised_finetuning.py` | `scripts/run_sft.sh` |
| On-Policy Distillation | 独立OPD蒸馏 | `training/opd_training.py` | `scripts/run_opd.sh` |
| Direct Preference Optimization | 直接偏好优化 | `training/dpo_training.py` | `scripts/run_dpo.sh` |
| Reward Modeling | 奖励模型建模 | `training/reward_modeling.py` | `scripts/run_rm.sh` |
| Reinforcement Learning | 强化学习 | `training/ppo_training.py` | `scripts/run_ppo.sh` |
| ORPO | 概率偏好优化 | `training/orpo_training.py` | `scripts/run_orpo.sh` |

## 快速开始

### 环境安装

```bash
pip install -r requirements.txt
```

### SFT训练示例

```bash
bash scripts/run_sft.sh
```

### DPO训练示例

```bash
bash scripts/run_dpo.sh
```

### vLLM部署

```bash
bash scripts/vllm_deployment.sh
```

## 支持的模型

| 模型 | 参数量 | Target Modules | 模板 |
|:-----|:-------|:---------------|:-----|
| Qwen2.5 | 0.5B/1.8B/4B/14B/72B | q_proj,v_proj | qwen |
| Qwen3 | 0.6B/1.7B/4B/8B/14B/32B/235B | q_proj,v_proj | qwen3 |
| Qwen3.5 | 0.8B/2B/4B/9B/27B/35B/122B | q_proj,v_proj | qwen3_5 |
| LLaMA2 | 7B/13B/70B | q_proj,v_proj | llama2 |
| LLaMA3 | 8B/70B | q_proj,v_proj | llama3 |
| Mistral | 7B/8x7B | q_proj,v_proj | mistral |
| Baichuan2 | 7B/13B | W_pack | baichuan2 |
| ChatGLM3 | 6B | query_key_value | chatglm3 |
| InternLM2 | 7B/20B | wqkv | intern2 |
| Yi | 6B/34B | q_proj,v_proj | yi |

## 显存需求参考

| 训练方法 | 精度 | 7B | 13B | 30B | 70B |
|:---------|:-----|:---|:----|:----|:----|
| 全参数 | AMP | 120GB | 240GB | 600GB | 1200GB |
| 全参数 | 16bit | 60GB | 120GB | 300GB | 600GB |
| LoRA | 16bit | 16GB | 32GB | 64GB | 160GB |
| QLoRA | 4bit | 6GB | 12GB | 24GB | 48GB |

## License

Apache License 2.0
