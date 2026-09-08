# 附录B 关键启动脚本与参数参考

## SFT训练脚本
**路径**：`scripts/run_sft.sh`

```bash
CUDA_VISIBLE_DEVICES=0,1 torchrun --nproc_per_node 2 training/supervised_finetuning.py \
    --model_name_or_path Qwen/Qwen3.5-0.8B \
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
    --save_total_limit 13 \
    --gradient_accumulation_steps 8 \
    --preprocessing_num_workers 4 \
    --output_dir outputs-sft-qwen-v1 \
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
    --cache_dir ./cache --flash_attn True
```

## DPO训练脚本
**路径**：`scripts/run_dpo.sh`

```bash
CUDA_VISIBLE_DEVICES=0,1 python3 training/dpo_training.py \
    --model_name_or_path Qwen/Qwen3.5-2B \
    --train_file_dir ./data/reward \
    --validation_file_dir ./data/reward \
    --per_device_train_batch_size 4 \
    --gradient_accumulation_steps 8 \
    --per_device_eval_batch_size 1 \
    --do_train \
    --do_eval \
    --use_peft True \
    --max_train_samples 1000 \
    --max_eval_samples 10 \
    --max_steps 100 \
    --eval_steps 20 \
    --save_steps 50 \
    --max_source_length 1024 \
    --max_target_length 512 \
    --output_dir outputs-dpo-qwen-v1 \
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

## 奖励模型训练脚本
**路径**：`scripts/run_rm.sh`

```bash
# reward model 训练暂不支持 torchrun 多卡训练
CUDA_VISIBLE_DEVICES=0,1 python3 training/reward_modeling.py \
    --model_name_or_path Qwen/Qwen3.5-2B \
    --train_file_dir ./data/reward \
    --validation_file_dir ./data/reward \
    --per_device_train_batch_size 4 \
    --gradient_accumulation_steps 8 \
    --per_device_eval_batch_size 4 \
    --do_train \
    --use_peft True \
    --seed 42 \
    --max_train_samples 1000 \
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
    --output_dir outputs-rm-qwen-v1 \
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

## PPO训练脚本
**路径**：`scripts/run_ppo.sh`

```bash
CUDA_VISIBLE_DEVICES=0,1 python3 training/ppo_training.py \
    --sft_model_path Qwen/Qwen3.5-2B \
    --reward_model_path Qwen/Qwen3.5-2B \
    --model_name_or_path Qwen/Qwen3.5-2B \
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
    --output_dir outputs-ppo-qwen-v1 \
    --eval_strategy steps \
    --eval_steps 100 \
    --num_train_epochs 3 \
    --report_to tensorboard
```

## vLLM部署脚本
**路径**：`scripts/vllm_deployment.sh`

```bash
export CUDA_VISIBLE_DEVICES=0,1

python3 -m vllm.entrypoints.openai.api_server \
    --model medical-model \
    --served-model-name doctor \
    --dtype=auto \
    --port 8000 \
    --host 0.0.0.0 \
    --gpu-memory-utilization 0.8 \
    --max-model-len 2048 \
    -tp 2 &
```

## DeepSpeed配置
- **ZeRO-2配置**：`scripts/zero2.json`
- **ZeRO-3配置**：`scripts/zero3.json`
