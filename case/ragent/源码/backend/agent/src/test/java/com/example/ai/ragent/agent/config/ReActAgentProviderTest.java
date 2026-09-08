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

import com.example.ai.ragent.agent.memory.AgentContextCompactionMiddleware;
import com.example.ai.ragent.agent.memory.AgentMemoryPipeline;
import com.example.ai.ragent.agent.memory.AgentMemoryProperties;
import com.example.ai.ragent.agent.memory.AgentUserMemoryMiddleware;
import com.example.ai.ragent.agent.service.AgentConversationService;
import com.example.ai.ragent.agent.state.PgAgentStateStore;
import com.example.ai.ragent.agent.tool.AgentToolCatalog;
import com.example.ai.ragent.agent.tool.KnowledgeSearchTool;
import com.example.ai.ragent.rag.core.intent.IntentNode;
import com.example.ai.ragent.rag.core.intent.IntentNodeRegistry;
import com.example.ai.ragent.rag.core.mcp.McpToolExecutor;
import com.example.ai.ragent.rag.core.mcp.McpToolRegistry;
import com.example.ai.ragent.rag.core.prompt.AgentPromptResolver;
import com.example.ai.ragent.rag.core.prompt.AgentPromptSlot;
import com.example.ai.ragent.rag.enums.IntentKind;
import com.example.ai.ragent.rag.service.KnowledgeSearchFacade;
import io.agentscope.extensions.model.openai.OpenAIChatModel;
import io.modelcontextprotocol.spec.McpSchema.CallToolResult;
import io.modelcontextprotocol.spec.McpSchema.JsonSchema;
import io.modelcontextprotocol.spec.McpSchema.Tool;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.spy;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class ReActAgentProviderTest {

    private IntentNodeRegistry intentNodeRegistry;
    private McpToolRegistry mcpToolRegistry;
    private AgentPromptResolver agentPromptResolver;
    private AgentToolCatalog toolCatalog;
    private ReActAgentProvider provider;

    @BeforeEach
    void setUp() {
        intentNodeRegistry = mock(IntentNodeRegistry.class);
        mcpToolRegistry = mock(McpToolRegistry.class);
        agentPromptResolver = mock(AgentPromptResolver.class);
        when(agentPromptResolver.resolve(AgentPromptSlot.AGENT_MAIN)).thenReturn("你是 Ragent");
        when(agentPromptResolver.resolve(AgentPromptSlot.KNOWLEDGE_TOOL_DESCRIPTION))
                .thenReturn("当前 Agent 的知识库工具描述");
        when(intentNodeRegistry.listMcpToolNodes()).thenReturn(List.of(
                mcpNode("sales", "销售查�?, "sales_query")));
        when(mcpToolRegistry.listAllExecutors()).thenReturn(List.of(executor("sales_query")));

        toolCatalog = spy(new AgentToolCatalog(
                mock(KnowledgeSearchFacade.class),
                mock(AgentConversationService.class),
                intentNodeRegistry,
                mcpToolRegistry,
                agentPromptResolver,
                new AgentMemoryProperties(),
                mock(AgentMemoryPipeline.class)));
        AgentProperties agentProperties = new AgentProperties();
        provider = new ReActAgentProvider(
                agentPromptResolver,
                toolCatalog,
                mock(OpenAIChatModel.class),
                mock(PgAgentStateStore.class),
                agentProperties,
                mock(AgentUserMemoryMiddleware.class),
                mock(AgentContextCompactionMiddleware.class));
    }

    @Test
    void shouldResolveToolCatalogOncePerRequest() {
        provider.getAgent();

        // 解析两次就有两份现实，指纹与 Toolkit 各信一份，中间注册表一变就长期不再自愈
        verify(toolCatalog, times(1)).resolve();
        verify(mcpToolRegistry, times(1)).listAllExecutors();
        verify(agentPromptResolver, times(1)).resolve(AgentPromptSlot.KNOWLEDGE_TOOL_DESCRIPTION);
    }

    @Test
    void shouldBuildToolkitFromTheSnapshotItsFingerprintCameFrom() {
        provider.getAgent();

        verify(toolCatalog, times(1)).buildToolkit(any(AgentToolCatalog.ResolvedCatalog.class));
    }

    @Test
    void shouldReuseCachedAgentWhenCatalogUnchanged() {
        var first = provider.getAgent();
        var second = provider.getAgent();

        assertThat(second.agent()).isSameAs(first.agent());
        assertThat(second.catalog()).isSameAs(first.catalog());
        verify(toolCatalog, times(1)).buildToolkit(any(AgentToolCatalog.ResolvedCatalog.class));
    }

    @Test
    void shouldRebuildWhenMcpToolAppears() {
        var first = provider.getAgent();
        when(mcpToolRegistry.listAllExecutors())
                .thenReturn(List.of(executor("sales_query"), executor("orders_query")));
        when(intentNodeRegistry.listMcpToolNodes()).thenReturn(List.of(
                mcpNode("sales", "销售查�?, "sales_query"),
                mcpNode("orders", "订单查询", "orders_query")));

        var second = provider.getAgent();

        assertThat(second.agent()).isNotSameAs(first.agent());
        assertThat(second.catalog().displayNameOf("orders_query")).isEqualTo("订单查询");
    }

    @Test
    void shouldCarryDisplayNamesOnSnapshot() {
        var active = provider.getAgent();

        assertThat(active.catalog().displayNameOf("sales_query")).isEqualTo("销售查�?);
        assertThat(active.catalog().displayNameOf(KnowledgeSearchTool.TOOL_NAME))
                .isEqualTo(KnowledgeSearchTool.DISPLAY_NAME);
        assertThat(active.catalog().displayNameOf("unknown_query")).isEqualTo("unknown_query");
    }

    private IntentNode mcpNode(String id, String name, String toolId) {
        return IntentNode.builder()
                .id(id)
                .name(name)
                .description("意图树描�?)
                .kind(IntentKind.MCP)
                .mcpToolId(toolId)
                .build();
    }

    private McpToolExecutor executor(String toolId) {
        Tool tool = Tool.builder()
                .name(toolId)
                .description("MCP 服务端描�?)
                .inputSchema(new JsonSchema("object", Map.of(), List.of(), false, null, null))
                .build();
        return new McpToolExecutor() {
            @Override
            public Tool getToolDefinition() {
                return tool;
            }

            @Override
            public CallToolResult execute(Map<String, Object> parameters) {
                return null;
            }
        };
    }
}
