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

package com.example.ai.ragent.agent.service.handler;

import com.example.ai.ragent.agent.dto.AgentBlock;
import com.example.ai.ragent.agent.service.AgentConversationService;
import com.example.ai.ragent.agent.tool.AgentToolCatalog.ResolvedCatalog;
import com.example.ai.ragent.framework.web.SseEmitterSender;
import com.example.ai.ragent.framework.web.StreamTaskManager;
import io.agentscope.core.event.TextBlockDeltaEvent;
import io.agentscope.core.event.ToolCallStartEvent;
import io.agentscope.core.event.ToolResultEndEvent;
import io.agentscope.core.event.ToolResultTextDeltaEvent;
import io.agentscope.core.message.ToolResultState;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class AgentStreamEventBridgeTest {

    private static final String TASK_ID = "t-9001";
    private static final String CONVERSATION_ID = "c-2002";
    private static final String USER_ID = "u-1001";

    private SseEmitterSender sender;
    private StreamTaskManager taskManager;
    private AgentConversationService conversationService;
    private AgentStreamEventBridge bridge;

    @BeforeEach
    void setUp() {
        sender = mock(SseEmitterSender.class);
        taskManager = mock(StreamTaskManager.class);
        conversationService = mock(AgentConversationService.class);
        bridge = newBridge();
    }

    @Test
    void shouldUnregisterTaskWhenStreamCompletes() {
        bridge.onComplete();

        verify(taskManager).unregister(TASK_ID);
        verify(sender).complete();
    }

    @Test
    void shouldUnregisterTaskWhenStreamFails() {
        when(taskManager.isCancelled(TASK_ID)).thenReturn(false);

        bridge.onError(new IllegalStateException("上游炸了"));

        verify(taskManager).unregister(TASK_ID);
        verify(sender).fail(any(Throwable.class));
    }

    @Test
    void shouldUnregisterTaskWhenStreamCancelled() {
        bridge.finishCancelledStream();

        // 三条收尾路应对称，取消路不注销会把清理甩给 30 分钟 TTL
        verify(taskManager).unregister(TASK_ID);
        verify(sender).complete();
    }

    @Test
    void shouldSettleOnlyOnceAcrossExits() {
        bridge.finishCancelledStream();
        bridge.onComplete();
        bridge.onComplete();

        // 取消先落地后，正常完成路必须整条哑火，不得重复落库或重复注销
        verify(conversationService, never()).addAssistantMessage(
                any(), any(), any(), any(), any(), any(), any());
        verify(taskManager, times(1)).unregister(TASK_ID);
    }

    @Test
    void shouldKeepStreamAliveWhenToolCallIdMissing() {
        // 不规范的 OpenAI 兼容端点会回�?toolCallId，空键进 ConcurrentHashMap 直接打断整条事件�?        bridge.onEvent(new ToolCallStartEvent("r-1", null, "search_knowledge"));
        bridge.onEvent(new ToolResultTextDeltaEvent("r-1", null, "search_knowledge", "命中三条"));
        bridge.onEvent(new ToolResultEndEvent("r-1", null, "search_knowledge", ToolResultState.SUCCESS));
        bridge.onComplete();

        assertThat(capturedBlocks()).singleElement().satisfies(block -> {
            assertThat(block.getStatus()).isEqualTo("done");
            assertThat(block.getResult()).isEqualTo("命中三条");
        });
    }

    @Test
    void shouldSettleOpenTextBlockWhenStreamCancelled() {
        bridge.onEvent(new TextBlockDeltaEvent("r-1", "b-1", "前半"));
        bridge.onEvent(new TextBlockDeltaEvent("r-1", "b-1", "后半"));

        bridge.finishCancelledStream();

        // 增量攒在缓冲里，定格这一刻才落成 String，取消路同样不能�?        assertThat(capturedBlocks()).singleElement().satisfies(block -> {
            assertThat(block.getKind()).isEqualTo("answer");
            assertThat(block.getText()).isEqualTo("前半后半");
        });
    }

    @Test
    void shouldSealTextBlockWhenToolStarts() {
        bridge.onEvent(new TextBlockDeltaEvent("r-1", "b-1", "先说一�?));
        bridge.onEvent(new ToolCallStartEvent("r-1", "call-1", "search_knowledge"));
        bridge.onEvent(new ToolResultEndEvent("r-1", "call-1", "search_knowledge", ToolResultState.SUCCESS));
        bridge.onEvent(new TextBlockDeltaEvent("r-1", "b-2", "再说一�?));
        bridge.onComplete();

        List<AgentBlock> blocks = capturedBlocks();
        assertThat(blocks).extracting(AgentBlock::getKind).containsExactly("answer", "tool", "answer");
        assertThat(blocks.get(0).getText()).isEqualTo("先说一�?);
        assertThat(blocks.get(2).getText()).isEqualTo("再说一�?);
    }

    @Test
    void shouldStampBlocksWithFullTimestamp() {
        bridge.onEvent(new TextBlockDeltaEvent("r-1", "b-1", "一句话"));
        bridge.onComplete();

        // 只存 HH:mm:ss，跨天会话回放时分不出这一行到底是哪天�?        String at = capturedBlocks().get(0).getAt();
        assertThat(LocalDateTime.parse(at).toLocalDate()).isEqualTo(LocalDate.now());
    }

    @SuppressWarnings("unchecked")
    private List<AgentBlock> capturedBlocks() {
        ArgumentCaptor<List<AgentBlock>> captor = ArgumentCaptor.forClass(List.class);
        verify(conversationService).addAssistantMessage(
                any(), any(), any(), any(), captor.capture(), any(), any());
        return captor.getValue();
    }

    private AgentStreamEventBridge newBridge() {
        return new AgentStreamEventBridge(AgentStreamEventBridge.Params.builder()
                .runHandle(new AgentRunHandle(TASK_ID, sender, taskManager))
                .conversationService(conversationService)
                .catalog(new ResolvedCatalog("知识库工具描�?, null, List.of(), List.of()))
                .conversationId(CONVERSATION_ID)
                .userId(USER_ID)
                .title("会话标题")
                .replyToMessageId("m-3003")
                .build());
    }
}
