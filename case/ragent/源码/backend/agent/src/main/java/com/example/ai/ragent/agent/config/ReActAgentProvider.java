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
import com.example.ai.ragent.agent.memory.AgentContextCompactionMiddleware;
import com.example.ai.ragent.agent.memory.AgentUserMemoryMiddleware;
import com.example.ai.ragent.agent.state.PgAgentStateStore;
import com.example.ai.ragent.agent.tool.AgentToolCatalog;
import com.example.ai.ragent.agent.tool.AgentToolCatalog.ResolvedCatalog;
import com.example.ai.ragent.rag.core.prompt.AgentPromptResolver;
import com.example.ai.ragent.rag.core.prompt.AgentPromptSlot;
import io.agentscope.core.ReActAgent;
import io.agentscope.extensions.model.openai.OpenAIChatModel;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

/**
 * �?Agent 供给器：单例复用，AGENT_MAIN 人设或工具目录变化时懒重�? * 会话状态在 PgAgentStateStore 中按次加载，重建不丢历史
 */
@Slf4j
@Component
@ConditionalOnAgentEngine
@RequiredArgsConstructor
public class ReActAgentProvider {

    private static final String AGENT_NAME = "ragent";

    private final AgentPromptResolver agentPromptResolver;
    private final AgentToolCatalog toolCatalog;
    private final OpenAIChatModel agentChatModel;
    private final PgAgentStateStore agentStateStore;
    private final AgentProperties agentProperties;
    private final AgentUserMemoryMiddleware userMemoryMiddleware;
    private final AgentContextCompactionMiddleware contextCompactionMiddleware;

    private volatile CachedAgent cached;

    /**
     * 以人设内容和工具目录签名判断重建时机：控制台修改后无需重启，下一次会话生�?     * 目录只解析一次，指纹�?Toolkit 同源，快照随实例一起返回给调用�?     */
    public ActiveAgent getAgent() {
        String persona = resolvePersona();
        ResolvedCatalog catalog = toolCatalog.resolve();
        CachedAgent current = cached;
        if (matches(current, persona, catalog)) {
            return new ActiveAgent(current.agent(), current.catalog());
        }
        synchronized (this) {
            current = cached;
            if (matches(current, persona, catalog)) {
                return new ActiveAgent(current.agent(), current.catalog());
            }
            // 旧实例不主动 close：在途会话仍在其上流式输出，交由 GC 回收
            ReActAgent agent = buildAgent(persona, catalog);
            cached = new CachedAgent(persona, catalog, agent);
            log.info("ReActAgent 已构�? maxIters: {}, maxRetries: {}",
                    agentProperties.getMaxIters(), agentProperties.getMaxRetries());
            return new ActiveAgent(agent, catalog);
        }
    }

    /**
     * 驱逐单个会话的内存状态：只作用于已构建的实例，清理动作不该顺手把 Agent 建起�?     * 仅本节点有效，多节点各持一份缓存，需要时�?Redis 广播补齐
     */
    @SuppressWarnings("resource")
    public void evictStateCache(String userId, String sessionId) {
        CachedAgent current = cached;
        if (current == null) {
            return;
        }
        current.agent().clearStateCache(userId, sessionId);
    }

    private boolean matches(CachedAgent current, String persona, ResolvedCatalog catalog) {
        return current != null
                && current.persona().equals(persona)
                && current.catalog().fingerprint().equals(catalog.fingerprint());
    }

    private ReActAgent buildAgent(String persona, ResolvedCatalog catalog) {
        return ReActAgent.builder()
                .name(AGENT_NAME)
                .sysPrompt(persona)
                .model(agentChatModel)
                .toolkit(toolCatalog.buildToolkit(catalog))
                .maxIters(agentProperties.getMaxIters())
                .maxRetries(agentProperties.getMaxRetries())
                .stateStore(agentStateStore)
                // 先注册即外层：记忆块插在人设与会话之间，压缩中间件的 offset 比对自然吸收这一�?                .middleware(userMemoryMiddleware)
                .middleware(contextCompactionMiddleware)
                .build();
    }

    private String resolvePersona() {
        String persona = agentPromptResolver.resolve(AgentPromptSlot.AGENT_MAIN);
        if (StrUtil.isBlank(persona)) {
            throw new IllegalStateException("Agent人设内容不允许为�?);
        }
        return persona;
    }

    /**
     * 本轮取到的实例与它构建时用的目录快照，成对交出免得调用方各自再取一�?     */
    public record ActiveAgent(ReActAgent agent, ResolvedCatalog catalog) {
    }

    private record CachedAgent(String persona, ResolvedCatalog catalog, ReActAgent agent) {
    }
}
