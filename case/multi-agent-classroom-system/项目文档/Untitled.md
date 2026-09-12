```
docker run -d \
  --gpus all \
  --name qwen3-30b1 \
  --restart unless-stopped \
  -p 8000:8000 \
  -v /ai/okwinds/Qwen3-30B-A3B-Instruct-2507-Int4-W4A16:/model \
  --shm-size=16g \
  -e CUDA_VISIBLE_DEVICES=0,1,2,3 \
  -e VLLM_ATTENTION_BACKEND=TRITON_ATTN \
  dd2af5422132 \
  /model \
  --host 0.0.0.0 \
  --port 8000 \
  --tensor-parallel-size 4 \
  --enable-expert-parallel \
  --dtype float16 \
  --max-model-len 120000 \
  --gpu-memory-utilization 0.90 \
  --max-num-seqs 1 \
  --enforce-eager \
  --served-model-name Qwen3-30B-A3B-Instruct-2507-Int4-W4A16 \
  --trust-remote-code \
  --enable-auto-tool-choice \
  --tool-call-parser her
  
  
curl http://192.168.110.90:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen3-30B-A3B-Instruct-2507-Int4-W4A16",
    "messages": [
      {
        "role": "user",
        "content": "请查询https://www.chzu.edu.cn/main.htm的基本信息。"
      }
    ],
    "tools": [
      {
        "type": "function",
        "function": {
          "name": "lookup_target",
          "description": "查询目标基本信息",
          "parameters": {
            "type": "object",
            "properties": {
              "target": {
                "type": "string"
              }
            },
            "required": ["target"]
          }
        }
      }
    ],
    "tool_choice": "auto",
    "temperature": 0.6,
    "max_tokens": 512
  }'
```

