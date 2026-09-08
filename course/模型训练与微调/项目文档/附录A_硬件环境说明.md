# 附录A 硬件环境说明

## 硬件配置
- **GPU**：2×A10‑24G（NVIDIA A10，24GB显存）
- **CPU**：建议8核以上
- **内存**：建议64GB以上
- **存储**：建议500GB以上SSD

## 软件环境
- **操作系统**：Ubuntu 20.04/22.04
- **Python**：3.8+
- **CUDA**：11.8+
- **PyTorch**：2.0+

## 依赖安装
```bash
# 安装项目依赖
pip install -r requirements.txt

# 关键依赖版本
# accelerate
# datasets>=2.14.6
# loguru
# peft>=0.19.1
# sentencepiece
# scikit-learn
# tensorboard
# tqdm>=4.47.0
# transformers>=5.6.0
# trl>=0.29.0
# bitsandbytes (需要从源码安装)
```

## 模型显存需求参考

| 训练方式 | 4B模型显存需求 | 7B模型显存需求 |
|---------|---------------|---------------|
| 全参数微调 | ~38GB | ~70GB（双卡） |
| LoRA | ~16GB | ~24GB |
| QLoRA | ~10GB | ~16GB |

> **说明**：4B模型在双A10可以真实跑通全参数微调，7B模型只能跑LoRA/QLoRA。
