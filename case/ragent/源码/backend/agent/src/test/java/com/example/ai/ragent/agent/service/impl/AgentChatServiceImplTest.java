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

package com.example.ai.ragent.agent.service.impl;

import com.example.ai.ragent.agent.config.ReActAgentProvider;
import com.example.ai.ragent.agent.config.ReActAgentProvider.ActiveAgent;
import com.example.ai.ragent.agent.enums.AgentMemoryTriggerType;
import com.example.ai.ragent.agent.memory.AgentMemoryOutcome;
import com.example.ai.ragent.agent.memory.AgentMemoryPipeline;
import com.example.ai.ragent.agent.memory.AgentMemoryProperties;
import com.example.ai.ragent.agent.service.AgentConversationService;
import com.example.ai.ragent.agent.service.handler.AgentRunGate;
import com.example.ai.ragent.agent.tool.AgentToolCatalog.ResolvedCatalog;
import com.example.ai.ragent.framework.context.LoginUser;
import com.example.ai.ragent.framework.context.UserContext;
import com.example.ai.ragent.framework.exception.ClientException;
import com.example.ai.ragent.framework.web.StreamTaskManager;
import io.agentscope.core.ReActAgent;
import io.agentscope.core.agent.RuntimeContext;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.InOrder;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import reactor.core.publisher.Flux;

import java.io.IOException;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.Consumer;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.atLeastOnce;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

class AgentChatServiceImplTest {

    private static final String USER_ID = "u-1001";
    private static final String CONVERSATION_ID = "c-2002";

    private ReActAgentProvider agentProvider;
    private AgentConversationService conversationService;
    private StreamTaskManager taskManager;
    private AgentRunGate runGate;
    private AgentMemoryProperties memoryProperties;
    private AgentMemoryPipeline memoryPipeline;
    private AtomicInteger gateReleased;
    private ReActAgent agent;
    private AgentChatServiceImpl service;

    @BeforeEach
    void setUp() {
        agentProvider = mock(ReActAgentProvider.class);
        conversationService = mock(AgentConversationService.class);
        taskManager = mock(StreamTaskManager.class);
        runGate = mock(AgentRunGate.class);
        agent = mock(ReActAgent.class);
        memoryProperties = new AgentMemoryProperties();
        memoryPipeline = mock(AgentMemoryPipeline.class);
        service = new AgentChatServiceImpl(agentProvider, conversationService, taskManager, runGate,
                memoryProperties, memoryPipeline);

        gateReleased = new AtomicInteger();
        when(runGate.acquire(anyString(), anyString(), anyString())).thenReturn(gateReleased::incrementAndGet);
        when(agentProvider.getAgent()).thenReturn(new ActiveAgent(
                agent, new ResolvedCatalog("知识库工具描�?, null, List.of(), List.of())));
        when(conversationService.touchConversation(anyString(), anyString(), anyString())).thenReturn("会话标题");
        when(conversationService.addUserMessage(anyString(), anyString(), anyString())).thenReturn("m-3003");
        // 每轮收尾都会调一次，不给默认结局其余用例会在后台线程上吃 NPE
        when(memoryPipeline.extract(anyString(), anyString(), any(AgentMemoryTriggerType.class)))
                .thenReturn(new AgentMemoryOutcome(AgentMemoryOutcome.Status.BELOW_THRESHOLD, 0, 1, false));
        UserContext.set(LoginUser.builder().userId(USER_ID).username("tester").build());
    }

    @AfterEach
    void tearDown() {
        UserContext.clear();
    }

    @Test
    void shouldEvictStateCacheWhenStreamCompletes() {
        when(agent.streamEvents(anyString(), any(RuntimeContext.class))).thenReturn(Flux.empty());

        service.streamChat("问题", CONVERSATION_ID, new SseEmitter());

        // 不驱逐则每个 (用户, 会话) 的全量记忆在单例 Agent 里常驻到进程重启
        verify(agentProvider).evictStateCache(USER_ID, CONVERSATION_ID);
    }

    /**
     * 轮次收尾触发抽取，且必须离开请求线程
     */
    @Test
    void shouldTriggerBackgroundExtractionOffTheRequestThread() throws Exception {
        CountDownLatch extracted = new CountDownLatch(1);
        AtomicReference<Thread> extractThread = new AtomicReference<>();
        AtomicInteger releasedWhenExtracting = new AtomicInteger(-1);
        when(memoryPipeline.extract(USER_ID, CONVERSATION_ID, AgentMemoryTriggerType.BACKGROUND))
                .thenAnswer(invocation -> {
                    extractThread.set(Thread.currentThread());
                    releasedWhenExtracting.set(gateReleased.get());
                    extracted.countDown();
                    return new AgentMemoryOutcome(AgentMemoryOutcome.Status.WRITTEN, 1, 3, true);
                });
        when(agent.streamEvents(anyString(), any(RuntimeContext.class))).thenReturn(Flux.empty());

        service.streamChat("问题", CONVERSATION_ID, new SseEmitter());

        assertThat(extracted.await(5, TimeUnit.SECONDS)).isTrue();
        assertThat(extractThread.get()).isNotSameAs(Thread.currentThread());
        assertThat(releasedWhenExtracting.get()).isEqualTo(1);
    }

    /**
     * 控制行建行时刻是抽取下界，必须先于本轮消息落库：反过来首条消息成「历史」，永久漏出抽取范围
     */
    @Test
    void shouldEnsureBaselineBeforeSavingUserMessage() {
        when(agent.streamEvents(anyString(), any(RuntimeContext.class))).thenReturn(Flux.empty());

        service.streamChat("我对花生严重过敏", CONVERSATION_ID, new SseEmitter());

        InOrder inOrder = inOrder(memoryPipeline, conversationService);
        inOrder.verify(memoryPipeline).ensureExtractionBaseline(USER_ID);
        inOrder.verify(conversationService).addUserMessage(CONVERSATION_ID, USER_ID, "我对花生严重过敏");
    }

    /**
     * 关掉开关连异步线程都不该起
     */
    @Test
    void shouldSkipBackgroundExtractionWhenLongTermDisabled() {
        memoryProperties.setLongTermEnabled(false);
        when(agent.streamEvents(anyString(), any(RuntimeContext.class))).thenReturn(Flux.empty());

        service.streamChat("问题", CONVERSATION_ID, new SseEmitter());

        verifyNoInteractions(memoryPipeline);
    }

    @Test
    void shouldEvictStateCacheWhenStreamCancelled() {
        // never 流不会自行走到完成路，驱逐只可能来自取消收尾
        when(agent.streamEvents(anyString(), any(RuntimeContext.class))).thenReturn(Flux.never());
        ArgumentCaptor<Runnable> finalizer = ArgumentCaptor.forClass(Runnable.class);

        service.streamChat("问题", CONVERSATION_ID, new SseEmitter());
        verify(taskManager).register(anyString(), anyString(), finalizer.capture());
        finalizer.getValue().run();

        verify(agentProvider).evictStateCache(USER_ID, CONVERSATION_ID);
    }

    @Test
    void shouldEvictOnlyOnceWhenCancelRacesCompletion() {
        when(agent.streamEvents(anyString(), any(RuntimeContext.class))).thenReturn(Flux.empty());
        ArgumentCaptor<Runnable> finalizer = ArgumentCaptor.forClass(Runnable.class);

        service.streamChat("问题", CONVERSATION_ID, new SseEmitter());
        verify(taskManager).register(anyString(), anyString(), finalizer.capture());
        finalizer.getValue().run();

        verify(agentProvider, times(1)).evictStateCache(USER_ID, CONVERSATION_ID);
    }

    @Test
    void shouldReleaseGateWhenStreamCompletes() {
        when(agent.streamEvents(anyString(), any(RuntimeContext.class))).thenReturn(Flux.empty());

        service.streamChat("问题", CONVERSATION_ID, new SseEmitter());

        // 闸门不还，该用户�?TTL 过期前发不出下一�?        assertThat(gateReleased.get()).isOne();
    }

    @Test
    void shouldReleaseGateWhenStreamCancelled() {
        when(agent.streamEvents(anyString(), any(RuntimeContext.class))).thenReturn(Flux.never());
        ArgumentCaptor<Runnable> finalizer = ArgumentCaptor.forClass(Runnable.class);

        service.streamChat("问题", CONVERSATION_ID, new SseEmitter());
        verify(taskManager).register(anyString(), anyString(), finalizer.capture());
        finalizer.getValue().run();

        assertThat(gateReleased.get()).isOne();
    }

    @Test
    void shouldReleaseGateWhenStartupFails() {
        when(conversationService.touchConversation(anyString(), anyString(), anyString()))
                .thenThrow(new IllegalStateException("库炸�?));

        assertThatThrownBy(() -> service.streamChat("问题", CONVERSATION_ID, new SseEmitter()))
                .isInstanceOf(IllegalStateException.class);

        // 启动期失败还没有收尾路可挂，闸门要就地归�?        assertThat(gateReleased.get()).isOne();
    }

    @Test
    void shouldReleaseGateWhenStartupThrowsError() {
        when(conversationService.touchConversation(anyString(), anyString(), anyString()))
                .thenThrow(new NoClassDefFoundError("类没�?));

        assertThatThrownBy(() -> service.streamChat("问题", CONVERSATION_ID, new SseEmitter()))
                .isInstanceOf(NoClassDefFoundError.class);

        // 只接 RuntimeException 的话，启动段�?Error 会把该用户挡�?TTL 过期（默认半小时�?        assertThat(gateReleased.get()).isOne();
    }

    @Test
    void shouldUnregisterTaskWhenStartupFails() {
        when(agent.streamEvents(anyString(), any(RuntimeContext.class)))
                .thenThrow(new IllegalStateException("上游没起�?));

        assertThatThrownBy(() -> service.streamChat("问题", CONVERSATION_ID, new SseEmitter()))
                .isInstanceOf(IllegalStateException.class);

        // �?register �?unregister 的任务会守灵�?30 分钟 TTL，期间还能被取消去戳已丢弃的 emitter
        verify(taskManager).unregister(anyString());
    }

    @Test
    void shouldNotStartRunWhenGateRejects() {
        when(runGate.acquire(anyString(), anyString(), anyString()))
                .thenThrow(new ClientException("当前会话处理中，请稍后再发起新的对话"));

        assertThatThrownBy(() -> service.streamChat("问题", CONVERSATION_ID, new SseEmitter()))
                .isInstanceOf(ClientException.class);

        // 被拒的请求不该留下会话行与任务登记，否则闸门反倒制造了脏数�?        verifyNoInteractions(conversationService);
        verifyNoInteractions(taskManager);
        verify(agent, never()).streamEvents(anyString(), any(RuntimeContext.class));
    }

    @Test
    void shouldCancelUpstreamWhenEmitterTimesOut() {
        when(agent.streamEvents(anyString(), any(RuntimeContext.class))).thenReturn(Flux.never());
        SseEmitter emitter = mock(SseEmitter.class);
        ArgumentCaptor<String> taskId = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<Runnable> callbacks = ArgumentCaptor.forClass(Runnable.class);

        service.streamChat("问题", CONVERSATION_ID, emitter);
        verify(taskManager).register(taskId.capture(), anyString(), any());
        verify(emitter, atLeastOnce()).onTimeout(callbacks.capture());
        callbacks.getAllValues().forEach(Runnable::run);

        // 超时只关响应不回收上游，ReAct 会在无人消费的情况下跑满迭代上限
        verify(taskManager).cancel(taskId.getValue());
    }

    @Test
    void shouldCancelUpstreamWhenEmitterErrors() {
        when(agent.streamEvents(anyString(), any(RuntimeContext.class))).thenReturn(Flux.never());
        SseEmitter emitter = mock(SseEmitter.class);
        ArgumentCaptor<String> taskId = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<Consumer<Throwable>> callbacks = ArgumentCaptor.forClass(Consumer.class);

        service.streamChat("问题", CONVERSATION_ID, emitter);
        verify(taskManager).register(taskId.capture(), anyString(), any());
        verify(emitter, atLeastOnce()).onError(callbacks.capture());
        callbacks.getAllValues().forEach(callback -> callback.accept(new IOException("客户端断开")));

        verify(taskManager).cancel(taskId.getValue());
    }

    @Test
    void shouldCancelUpstreamWhenEmitterClosesWithoutSettling() {
        when(agent.streamEvents(anyString(), any(RuntimeContext.class))).thenReturn(Flux.never());
        SseEmitter emitter = mock(SseEmitter.class);
        ArgumentCaptor<String> taskId = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<Runnable> callbacks = ArgumentCaptor.forClass(Runnable.class);

        service.streamChat("问题", CONVERSATION_ID, emitter);
        verify(taskManager).register(taskId.capture(), anyString(), any());
        verify(emitter, atLeastOnce()).onCompletion(callbacks.capture());
        callbacks.getAllValues().forEach(Runnable::run);

        // 关页导致写失败时容器不报超时也不报错，只�?completion 回调兜得�?        verify(taskManager).cancel(taskId.getValue());
    }

    @Test
    void shouldNotCancelAfterRunAlreadySettled() {
        when(agent.streamEvents(anyString(), any(RuntimeContext.class))).thenReturn(Flux.empty());
        SseEmitter emitter = mock(SseEmitter.class);
        ArgumentCaptor<Runnable> callbacks = ArgumentCaptor.forClass(Runnable.class);

        service.streamChat("问题", CONVERSATION_ID, emitter);
        verify(emitter, atLeastOnce()).onCompletion(callbacks.capture());
        callbacks.getAllValues().forEach(Runnable::run);

        // 正常完成也会触发 completion 回调，这里再取消等于每个请求都往 Redis 写一�?30 分钟死标�?        verify(taskManager, never()).cancel(anyString());
    }
}
