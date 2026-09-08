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

package com.example.ai.ragent.agent.tool;

import com.example.ai.ragent.agent.service.AgentConversationService;
import com.example.ai.ragent.framework.convention.ChatMessage;
import com.example.ai.ragent.rag.service.KnowledgeSearchFacade;
import io.agentscope.core.agent.RuntimeContext;
import io.agentscope.core.message.TextBlock;
import io.agentscope.core.message.ToolResultBlock;
import io.agentscope.core.message.ToolResultState;
import io.agentscope.core.tool.ToolCallParam;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class KnowledgeSearchToolTest {

    @Test
    void shouldExposeConfiguredDescriptionAndDelegateSearch() {
        KnowledgeSearchFacade knowledgeSearchFacade = mock(KnowledgeSearchFacade.class);
        AgentConversationService conversationService = mock(AgentConversationService.class);
        List<ChatMessage> recentTurns = List.of(
                ChatMessage.user("差旅报销走什么流�?),
                ChatMessage.assistant("先在 OA 提交申请�?));
        when(conversationService.loadRecentTurns("conversation-1", "user-1", 2))
                .thenReturn(recentTurns);
        when(knowledgeSearchFacade.search("需要哪些材�?, recentTurns)).thenReturn("需要发票和审批�?);
        KnowledgeSearchTool tool = new KnowledgeSearchTool(
                "检索当�?Agent 的企业知识库", knowledgeSearchFacade, conversationService);
        ToolCallParam param = ToolCallParam.builder()
                .input(Map.of("query", " 需要哪些材�?"))
                .runtimeContext(RuntimeContext.builder()
                        .sessionId("conversation-1")
                        .userId("user-1")
                        .build())
                .build();

        ToolResultBlock result = tool.callAsync(param).block();

        assertThat(tool.getName()).isEqualTo(KnowledgeSearchTool.TOOL_NAME);
        assertThat(tool.getDescription()).isEqualTo("检索当�?Agent 的企业知识库");
        assertThat(tool.getParameters()).containsEntry("required", List.of("query"));
        assertThat(result).isNotNull();
        assertThat(result.getState()).isEqualTo(ToolResultState.SUCCESS);
        assertThat(((TextBlock) result.getOutput().get(0)).getText()).isEqualTo("需要发票和审批�?);
        verify(knowledgeSearchFacade).search("需要哪些材�?, recentTurns);
    }

    @Test
    void shouldRejectBlankQueryWithoutSearching() {
        KnowledgeSearchFacade knowledgeSearchFacade = mock(KnowledgeSearchFacade.class);
        KnowledgeSearchTool tool = new KnowledgeSearchTool(
                "检索企业知识库", knowledgeSearchFacade, mock(AgentConversationService.class));

        ToolResultBlock result = tool.callAsync(ToolCallParam.builder()
                        .input(Map.of("query", " "))
                        .build())
                .block();

        assertThat(result).isNotNull();
        assertThat(result.getState()).isEqualTo(ToolResultState.ERROR);
        assertThat(((TextBlock) result.getOutput().get(0)).getText()).contains("query 不能为空");
        verify(knowledgeSearchFacade, never())
                .search(org.mockito.ArgumentMatchers.any(), org.mockito.ArgumentMatchers.any());
    }
}
