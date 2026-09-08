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

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.example.ai.ragent.agent.config.ReActAgentProvider;
import com.example.ai.ragent.agent.dao.entity.AgentConversationDO;
import com.example.ai.ragent.agent.dao.entity.AgentMessageDO;
import com.example.ai.ragent.agent.dao.mapper.AgentConversationMapper;
import com.example.ai.ragent.agent.dao.mapper.AgentMessageMapper;
import com.example.ai.ragent.agent.enums.AgentMessageStatus;
import com.example.ai.ragent.agent.service.handler.AgentRunGate;
import com.example.ai.ragent.agent.state.PgAgentStateStore;
import com.example.ai.ragent.framework.convention.ChatMessage;
import com.example.ai.ragent.framework.web.StreamTaskManager;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.InOrder;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import java.util.Date;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class AgentConversationServiceImplTest {

    private static final String USER_ID = "u-1001";
    private static final String CONVERSATION_ID = "c-2002";
    private static final int TURNS = 2;
    private static final Pattern SCAN_LIMIT = Pattern.compile("limit\\s+(\\d+)");

    static {
        // 脱离 SqlSession �?lambda 列名缓存是空的，条件构造器取不�?SQL 片段
        TableInfoHelper.initTableInfo(
                new MapperBuilderAssistant(new MybatisConfiguration(), ""), AgentMessageDO.class);
    }

    private AgentConversationMapper conversationMapper;
    private AgentMessageMapper messageMapper;
    private PgAgentStateStore agentStateStore;
    private AgentRunGate runGate;
    private StreamTaskManager taskManager;
    private ReActAgentProvider agentProvider;
    private AgentConversationServiceImpl service;

    @BeforeEach
    @SuppressWarnings("unchecked")
    void setUp() {
        conversationMapper = mock(AgentConversationMapper.class);
        messageMapper = mock(AgentMessageMapper.class);
        agentStateStore = mock(PgAgentStateStore.class);
        runGate = mock(AgentRunGate.class);
        taskManager = mock(StreamTaskManager.class);
        agentProvider = mock(ReActAgentProvider.class);
        ObjectProvider<ReActAgentProvider> agentProviderRef = mock(ObjectProvider.class);
        when(agentProviderRef.getIfAvailable()).thenReturn(agentProvider);
        when(conversationMapper.delete(any())).thenReturn(1);
        when(messageMapper.delete(any())).thenReturn(1);
        service = new AgentConversationServiceImpl(
                conversationMapper, messageMapper, agentStateStore, runGate, taskManager, agentProviderRef);
    }

    @AfterEach
    void tearDown() {
        if (TransactionSynchronizationManager.isSynchronizationActive()) {
            TransactionSynchronizationManager.clearSynchronization();
        }
    }

    @Test
    void shouldEvictAgentStateCacheWhenConversationDeleted() {
        service.delete(CONVERSATION_ID, USER_ID);

        // 表清了内存不清，单例 Agent 会带着已删记忆继续对话并把状态写�?PG
        verify(agentProvider).evictStateCache(USER_ID, CONVERSATION_ID);
    }

    @Test
    void shouldEvictEachConversationWhenBatchDeleted() {
        service.deleteBatch(List.of(CONVERSATION_ID, "c-3003", CONVERSATION_ID), USER_ID);

        // 重复 ID 去重后每个会话各驱逐一�?        verify(agentProvider, times(1)).evictStateCache(USER_ID, CONVERSATION_ID);
        verify(agentProvider, times(1)).evictStateCache(USER_ID, "c-3003");
    }

    @Test
    void shouldEvictOnlyAfterTransactionCommits() {
        TransactionSynchronizationManager.initSynchronization();

        service.delete(CONVERSATION_ID, USER_ID);

        // 事务还没提就驱逐内存，一旦回滚就成了表还在记忆没�?        verify(agentProvider, never()).evictStateCache(USER_ID, CONVERSATION_ID);
        commitCurrentTransaction();
        verify(agentProvider).evictStateCache(USER_ID, CONVERSATION_ID);
    }

    @Test
    void shouldEvictBatchAfterSingleCommit() {
        TransactionSynchronizationManager.initSynchronization();

        service.deleteBatch(List.of(CONVERSATION_ID, "c-3003"), USER_ID);

        verify(agentProvider, never()).evictStateCache(any(), any());
        commitCurrentTransaction();
        verify(agentProvider, times(1)).evictStateCache(USER_ID, CONVERSATION_ID);
        verify(agentProvider, times(1)).evictStateCache(USER_ID, "c-3003");
    }

    @Test
    void shouldCancelRunningStreamOfDeletedConversation() {
        when(runGate.runningTaskId(USER_ID, CONVERSATION_ID)).thenReturn("t-9001");

        service.delete(CONVERSATION_ID, USER_ID);

        // 流不停就会跑到底，把记忆写回 PG、把打断消息插回来，正是「删了又活」的那条�?        verify(taskManager).cancel("t-9001");
    }

    @Test
    void shouldNotTouchStreamOfAnotherConversation() {
        // 该用户确实有流在跑，但跑的是别的会话
        when(runGate.runningTaskId(USER_ID, CONVERSATION_ID)).thenReturn(null);

        service.delete(CONVERSATION_ID, USER_ID);

        verify(taskManager, never()).cancel(any());
    }

    @Test
    void shouldPurgeResidueWhenConversationRecreated() {
        // 会话行查不到就要建：同号的状态与消息只可能是删除后的残骸
        when(conversationMapper.selectOne(any())).thenReturn(null);

        service.touchConversation(CONVERSATION_ID, USER_ID, "本轮提问");

        verify(agentStateStore).delete(USER_ID, CONVERSATION_ID);
        verify(messageMapper).delete(any());
        verify(agentProvider).evictStateCache(USER_ID, CONVERSATION_ID);
    }

    @Test
    void shouldPurgeBeforeCreatingConversationRow() {
        when(conversationMapper.selectOne(any())).thenReturn(null);
        InOrder order = inOrder(agentStateStore, conversationMapper);

        service.touchConversation(CONVERSATION_ID, USER_ID, "本轮提问");

        // 清失败就不该建行：留下「会话行是新的、记忆是旧的」比不建更糟，重试还会再清一�?        order.verify(agentStateStore).delete(USER_ID, CONVERSATION_ID);
        order.verify(conversationMapper).insert(any(AgentConversationDO.class));
    }

    @Test
    void shouldNotPurgeWhenConversationStillAlive() {
        when(conversationMapper.selectOne(any())).thenReturn(existingConversation("老会�?));

        service.touchConversation(CONVERSATION_ID, USER_ID, "本轮提问");

        // 会话还活着，清就是把用户的记忆和消息删�?        verify(agentStateStore, never()).delete(any(), any());
        verify(messageMapper, never()).delete(any());
        verify(agentProvider, never()).evictStateCache(any(), any());
    }

    @Test
    void shouldDeclareTransactionOnDeletePaths() throws NoSuchMethodException {
        // 三步删中途失败会留半删状态，注解掉了就没人拦
        assertThat(AgentConversationServiceImpl.class
                .getDeclaredMethod("delete", String.class, String.class)
                .getAnnotation(Transactional.class)).isNotNull();
        assertThat(AgentConversationServiceImpl.class
                .getDeclaredMethod("deleteBatch", List.class, String.class)
                .getAnnotation(Transactional.class)).isNotNull();
    }

    @Test
    void shouldReturnExistingTitleWhenInsertLosesRace() {
        // 并发首问：两侧都查空各自插入，落败方撞唯一索引
        when(conversationMapper.selectOne(any())).thenReturn(null, existingConversation("赢家标题"));
        when(conversationMapper.insert(any(AgentConversationDO.class)))
                .thenThrow(new DuplicateKeyException("uk_agent_conversation_user"));

        String title = service.touchConversation(CONVERSATION_ID, USER_ID, "本轮提问");

        assertThat(title).isEqualTo("赢家标题");
        verify(conversationMapper, times(2)).selectOne(any());
    }

    @Test
    void shouldRethrowWhenDuplicateKeyIsNotRecoverable() {
        // 撞键却重查不到，说明冲突另有来源，不能吞�?        when(conversationMapper.selectOne(any())).thenReturn(null, (AgentConversationDO) null);
        when(conversationMapper.insert(any(AgentConversationDO.class)))
                .thenThrow(new DuplicateKeyException("uk_agent_conversation_user"));

        assertThatThrownBy(() -> service.touchConversation(CONVERSATION_ID, USER_ID, "本轮提问"))
                .isInstanceOf(DuplicateKeyException.class);
    }

    @Test
    void shouldSkipTurnWhoseAnswerWasInterrupted() {
        // 倒序：本轮提�?�?被打断的半截�?�?其提�?�?完整�?�?其提�?        stubMessages(List.of(
                userRow("m-5", "第三�?),
                assistantRow("m-4", "m-3", "半截", AgentMessageStatus.INTERRUPTED),
                userRow("m-3", "第二�?),
                assistantRow("m-2", "m-1", "第一�?, AgentMessageStatus.NORMAL),
                userRow("m-1", "第一�?)));

        List<ChatMessage> history = service.loadRecentTurns(CONVERSATION_ID, USER_ID, TURNS);

        // 半截答案进了改写上下文，等于拿没说完的话当事�?        assertThat(history).extracting(ChatMessage::getContent).containsExactly("第一�?, "第一�?);
    }

    @Test
    void shouldDropQuestionWhoseAnswerWasNeverPersisted() {
        // 取消时一个字都没生成，assistant 行压根不落库
        stubMessages(List.of(
                userRow("m-4", "第三�?),
                userRow("m-3", "第二�?),
                assistantRow("m-2", "m-1", "第一�?, AgentMessageStatus.NORMAL),
                userRow("m-1", "第一�?)));

        List<ChatMessage> history = service.loadRecentTurns(CONVERSATION_ID, USER_ID, TURNS);

        assertThat(history).extracting(ChatMessage::getContent).containsExactly("第一�?, "第一�?);
        assertThat(history).extracting(ChatMessage::getRole)
                .containsExactly(ChatMessage.Role.USER, ChatMessage.Role.ASSISTANT);
    }

    @Test
    void shouldWidenScanWindowBeyondTargetPairs() {
        stubMessages(List.of());

        service.loadRecentTurns(CONVERSATION_ID, USER_ID, TURNS);

        // 窗口只够 N 对时，中途作废一轮就凑不�?N 对，扫描量得留出作废余量
        assertThat(capturedScanLimit()).isGreaterThan(TURNS * 2 + 1);
    }

    private void stubMessages(List<AgentMessageDO> latestFirst) {
        when(messageMapper.selectList(any())).thenReturn(latestFirst);
    }

    private static AgentMessageDO userRow(String id, String content) {
        return AgentMessageDO.builder()
                .id(id)
                .role("user")
                .content(content)
                .messageStatus(AgentMessageStatus.NORMAL.name())
                .build();
    }

    private static AgentMessageDO assistantRow(String id, String replyTo, String content, AgentMessageStatus status) {
        return AgentMessageDO.builder()
                .id(id)
                .role("assistant")
                .content(content)
                .replyToMessageId(replyTo)
                .messageStatus(status.name())
                .build();
    }

    /**
     * 从查询条件尾巴里抠出扫描行数，用来证明窗口留了余�?     */
    @SuppressWarnings("unchecked")
    private int capturedScanLimit() {
        ArgumentCaptor<Wrapper<AgentMessageDO>> captor = ArgumentCaptor.forClass(Wrapper.class);
        verify(messageMapper).selectList(captor.capture());
        Matcher matcher = SCAN_LIMIT.matcher(captor.getValue().getSqlSegment());
        assertThat(matcher.find()).isTrue();
        return Integer.parseInt(matcher.group(1));
    }

    /**
     * 模拟事务提交：驱动已注册的同步回调走 afterCommit
     */
    private void commitCurrentTransaction() {
        List.copyOf(TransactionSynchronizationManager.getSynchronizations())
                .forEach(TransactionSynchronization::afterCommit);
    }

    private AgentConversationDO existingConversation(String title) {
        return AgentConversationDO.builder()
                .conversationId(CONVERSATION_ID)
                .userId(USER_ID)
                .title(title)
                .lastTime(new Date())
                .build();
    }
}
