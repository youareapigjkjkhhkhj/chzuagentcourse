-- 添加 embedding_api_url 字段到 knowledge_base_settings 表
-- 迁移脚本: 003_add_embedding_api_url.sql

-- 检查字段是否已存在，如果不存在则添加
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_name = 'knowledge_base_settings' 
        AND column_name = 'embedding_api_url'
    ) THEN
        ALTER TABLE knowledge_base_settings 
        ADD COLUMN embedding_api_url VARCHAR(500);
        
        COMMENT ON COLUMN knowledge_base_settings.embedding_api_url IS '嵌入模型 API 地址';
    END IF;
END $$;

-- 对于已存在的设置记录，尝试从模型配置中填充 API URL
-- 注意：这需要 model_configs 表存在
DO $$
DECLARE
    settings_record RECORD;
    model_record RECORD;
    api_url TEXT;
BEGIN
    -- 遍历所有设置记录
    FOR settings_record IN 
        SELECT id, embedding_model, embedding_api_url 
        FROM knowledge_base_settings 
        WHERE embedding_api_url IS NULL OR embedding_api_url = ''
    LOOP
        -- 查找对应的模型配置
        SELECT api_endpoint INTO model_record
        FROM model_configs
        WHERE model_name = settings_record.embedding_model
        AND type = 'embedding'
        LIMIT 1;
        
        -- 如果找到模型配置，更新 API URL
        IF FOUND AND model_record.api_endpoint IS NOT NULL THEN
            api_url := model_record.api_endpoint;
            
            -- 确保 URL 包含 /api/embeddings 路径
            IF api_url NOT LIKE '%/api/embeddings' AND api_url NOT LIKE '%/embeddings' THEN
                api_url := api_url || '/api/embeddings';
            END IF;
            
            UPDATE knowledge_base_settings
            SET embedding_api_url = api_url
            WHERE id = settings_record.id;
            
            RAISE NOTICE 'Updated embedding_api_url for settings id=%: %', settings_record.id, api_url;
        END IF;
    END LOOP;
END $$;
