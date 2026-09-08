/*
 * Licensed to the Apache Software Foundation (ASF) under one or more
 * contributor license agreements.  See the NOTICE file distributed with
 * this work for additional information regarding copyright ownership.
 * The ASF licenses this file to You under the Apache License, Version 2.0
 * (the "License"); you may not use this file except in compliance with
 * the License.  You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

package com.example.ai.ragent.agent.config;

import cn.hutool.core.util.StrUtil;
import com.example.ai.ragent.agent.dao.mapper.AgentStateMapper;
import com.example.ai.ragent.agent.state.PgAgentStateStore;
import com.example.ai.ragent.infra.config.AIModelProperties;
import io.agentscope.extensions.model.openai.OpenAIChatModel;
import lombok.RequiredArgsConstructor;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.util.Map;

/**
 * Agent 引擎装配：模型与状态存�? * MCP 不走 AgentScope 自带客户端（�?MCP SDK 0.17.0 被根 pom �?1.1.2 压制），统一桥接 rag 既有连接
 */
@Configuration
@ConditionalOnAgentEngine
@RequiredArgsConstructor
public class AgentEngineConfiguration {

    private final AgentProperties agentProperties;
    private final AIModelProperties aiModelProperties;

    @Bean
    public OpenAIChatModel agentChatModel() {
        AgentProperties.Chat chat = agentProperties.getChat();
        if (chat == null || StrUtil.isBlank(chat.getProvider()) || StrUtil.isBlank(chat.getModel())) {
            throw new IllegalStateException("agent.chat.provider / agent.chat.model 未配�?);
        }

        Map<String, AIModelProperties.ProviderConfig> providers = aiModelProperties.getProviders();
        AIModelProperties.ProviderConfig provider = providers == null ? null : providers.get(chat.getProvider());
        if (provider == null) {
            throw new IllegalStateException("agent.chat.provider �?ai.providers 中不存在: " + chat.getProvider());
        }
        String endpointPath = provider.getEndpoints() == null ? null : provider.getEndpoints().get("chat");
        if (StrUtil.isBlank(provider.getUrl()) || StrUtil.isBlank(endpointPath)) {
            throw new IllegalStateException("供应商缺�?url �?endpoints.chat: " + chat.getProvider());
        }

        return OpenAIChatModel.builder()
                .baseUrl(provider.getUrl())
                .endpointPath(endpointPath)
                .apiKey(provider.getApiKey())
                .modelName(chat.getModel())
                .stream(true)
                // 兼容端点普遍无法同时处理 response_format 与工具调用，统一�?generate_response 兜底
                .nativeStructuredOutputWithTools(false)
                .build();
    }

    @Bean
    public PgAgentStateStore agentStateStore(AgentStateMapper agentStateMapper) {
        return new PgAgentStateStore(agentStateMapper);
    }
}
