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

import cn.hutool.core.collection.CollUtil;
import cn.hutool.core.util.StrUtil;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.example.ai.ragent.agent.config.ConditionalOnAgentEngine;
import com.example.ai.ragent.agent.config.ReActAgentProvider;
import com.example.ai.ragent.agent.controller.vo.AgentConversationVO;
import com.example.ai.ragent.agent.controller.vo.AgentMessageVO;
import com.example.ai.ragent.agent.dao.entity.AgentConversationDO;
import com.example.ai.ragent.agent.dao.entity.AgentMessageDO;
import com.example.ai.ragent.agent.dao.mapper.AgentConversationMapper;
import com.example.ai.ragent.agent.dao.mapper.AgentMessageMapper;
import com.example.ai.ragent.agent.dto.AgentBlock;
import com.example.ai.ragent.agent.enums.AgentMessageStatus;
import com.example.ai.ragent.agent.service.AgentConversationService;
import com.example.ai.ragent.agent.service.handler.AgentRunGate;
import com.example.ai.ragent.agent.state.PgAgentStateStore;
import com.example.ai.ragent.framework.convention.ChatMessage;
import com.example.ai.ragent.framework.exception.ClientException;
import com.example.ai.ragent.framework.web.StreamTaskManager;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import java.util.ArrayList;
import java.util.Collections;
import java.util.Date;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * Agent 会话存储实现，展示层数据�?AgentScope 状态互不掺�? */
@Slf4j
@Service
@ConditionalOnAgentEngine
@RequiredArgsConstructor
public class AgentConversationServiceImpl implements AgentConversationService {

    private static final int TITLE_MAX_LENGTH = 30;
    private static final int RENAME_MAX_LENGTH = 128;
    private static final String ROLE_USER = "user";
    private static final String ROLE_ASSISTANT = "assistant";

    private final AgentConversationMapper conversationMapper;
    private final AgentMessageMapper messageMapper;
    private final PgAgentStateStore agentStateStore;
    private final AgentRunGate runGate;
    private final StreamTaskManager taskManager;
    /**
     * 惰性取用：Provider 经工具目录反向依赖本服务，构造期注入会成�?     */
    private final ObjectProvider<ReActAgentProvider> agentProviderRef;

    @Override
    public String touchConversation(String conversationId, String userId, String question) {
        AgentConversationDO existing = selectConversation(conversationId, userId);
        if (existing != null) {
            return touchLastTime(existing);
        }
        purgeResidue(conversationId, userId);

        // v1 简化：截断首问作标题，不走 LLM 生成
        String title = StrUtil.sub(StrUtil.emptyIfNull(question).trim(), 0, TITLE_MAX_LENGTH);
        AgentConversationDO conversation = AgentConversationDO.builder()
                .conversationId(conversationId)
                .userId(userId)
                .title(title)
                .lastTime(new Date())
                .build();
        try {
            conversationMapper.insert(conversation);
        } catch (DuplicateKeyException dke) {
            // 同会话并发首问，落败方重查赢家；查不到说明冲突另有来源，交由上层处理
            AgentConversationDO winner = selectConversation(conversationId, userId);
            if (winner == null) {
                throw dke;
            }
            return touchLastTime(winner);
        }
        return title;
    }

    private AgentConversationDO selectConversation(String conversationId, String userId) {
        return conversationMapper.selectOne(Wrappers.lambdaQuery(AgentConversationDO.class)
                .eq(AgentConversationDO::getConversationId, conversationId)
                .eq(AgentConversationDO::getUserId, userId));
    }

    private String touchLastTime(AgentConversationDO conversation) {
        conversation.setLastTime(new Date());
        conversationMapper.updateById(conversation);
        return conversation.getTitle();
    }

    /**
     * 会话行不在了，同号的状态与消息只可能是残骸：删除时的在途流会在事务提交之后才把记忆写回、把打断消息插进�?     * 清在建行之前——清失败就不建行，重试还会再清一遍，不至于留下「会话行是新的、记忆是旧的」这种会�?     * 顺带把本节点的内存记忆一并驱逐：重开会话的请求落在哪个节点，要用缓存的就是哪个节�?     */
    private void purgeResidue(String conversationId, String userId) {
        agentStateStore.delete(userId, conversationId);
        messageMapper.delete(Wrappers.lambdaQuery(AgentMessageDO.class)
                .eq(AgentMessageDO::getConversationId, conversationId)
                .eq(AgentMessageDO::getUserId, userId));
        evictStateCache(userId, conversationId);
    }

    @Override
    public String addUserMessage(String conversationId, String userId, String content) {
        AgentMessageDO message = AgentMessageDO.builder()
                .conversationId(conversationId)
                .userId(userId)
                .role(ROLE_USER)
                .content(content)
                .messageStatus(AgentMessageStatus.NORMAL.name())
                .build();
        messageMapper.insert(message);
        return message.getId();
    }

    @Override
    public String addAssistantMessage(String conversationId, String userId, String content, String thinkingContent,
                                      List<AgentBlock> blocks, String replyToMessageId, AgentMessageStatus status) {
        AgentMessageDO message = AgentMessageDO.builder()
                .conversationId(conversationId)
                .userId(userId)
                .role(ROLE_ASSISTANT)
                .content(content)
                .thinkingContent(StrUtil.blankToDefault(thinkingContent, null))
                .blocks(blocks)
                .replyToMessageId(replyToMessageId)
                .messageStatus(status.name())
                .build();
        messageMapper.insert(message);
        return message.getId();
    }

    @Override
    public List<AgentConversationVO> listByUserId(String userId) {
        List<AgentConversationDO> conversations = conversationMapper.selectList(
                Wrappers.lambdaQuery(AgentConversationDO.class)
                        .eq(AgentConversationDO::getUserId, userId)
                        .orderByDesc(AgentConversationDO::getLastTime));
        Map<String, Long> turnCounts = countTurns(conversations, userId);
        return conversations.stream()
                .map(item -> AgentConversationVO.builder()
                        .conversationId(item.getConversationId())
                        .title(item.getTitle())
                        .lastTime(item.getLastTime())
                        .turns(turnCounts.getOrDefault(item.getConversationId(), 0L).intValue())
                        .build())
                .toList();
    }

    /**
     * 每会话的用户提问数即轮数，一�?groupBy 拉全量避�?N+1
     */
    private Map<String, Long> countTurns(List<AgentConversationDO> conversations, String userId) {
        if (conversations.isEmpty()) {
            return Map.of();
        }
        List<String> ids = conversations.stream().map(AgentConversationDO::getConversationId).toList();
        QueryWrapper<AgentMessageDO> query = new QueryWrapper<AgentMessageDO>()
                .select("conversation_id", "COUNT(*) AS turn_count")
                .eq("user_id", userId)
                .eq("role", ROLE_USER)
                .in("conversation_id", ids)
                .groupBy("conversation_id");
        return messageMapper.selectMaps(query).stream()
                .collect(Collectors.toMap(
                        row -> String.valueOf(row.get("conversation_id")),
                        row -> ((Number) row.get("turn_count")).longValue()));
    }

    @Override
    public void rename(String conversationId, String userId, String title) {
        String trimmed = StrUtil.trimToEmpty(title);
        if (trimmed.isEmpty()) {
            throw new ClientException("会话标题不能为空");
        }
        AgentConversationDO conversation = conversationMapper.selectOne(
                Wrappers.lambdaQuery(AgentConversationDO.class)
                        .eq(AgentConversationDO::getConversationId, conversationId)
                        .eq(AgentConversationDO::getUserId, userId));
        if (conversation == null) {
            throw new ClientException("会话不存�?);
        }
        conversation.setTitle(StrUtil.sub(trimmed, 0, RENAME_MAX_LENGTH));
        conversationMapper.updateById(conversation);
    }

    @Override
    public List<AgentMessageVO> listMessages(String conversationId, String userId) {
        return messageMapper.selectList(Wrappers.lambdaQuery(AgentMessageDO.class)
                        .eq(AgentMessageDO::getConversationId, conversationId)
                        .eq(AgentMessageDO::getUserId, userId)
                        .orderByAsc(AgentMessageDO::getId))
                .stream()
                .map(item -> AgentMessageVO.builder()
                        .id(item.getId())
                        .role(item.getRole())
                        .content(item.getContent())
                        .thinkingContent(item.getThinkingContent())
                        .blocks(item.getBlocks())
                        .messageStatus(item.getMessageStatus())
                        .createTime(item.getCreateTime())
                        .build())
                .toList();
    }

    /**
     * �?replyToMessageId 配成「提�?+ 回答」对后取最�?N 对，只取正文——blocks 里的工具结果动辄上万�?     */
    @Override
    public List<ChatMessage> loadRecentTurns(String conversationId, String userId, int turns) {
        if (StrUtil.isBlank(conversationId) || StrUtil.isBlank(userId) || turns <= 0) {
            return List.of();
        }
        List<AgentMessageDO> latestFirst = messageMapper.selectList(Wrappers.lambdaQuery(AgentMessageDO.class)
                .eq(AgentMessageDO::getConversationId, conversationId)
                .eq(AgentMessageDO::getUserId, userId)
                .orderByDesc(AgentMessageDO::getId)
                .last("limit " + scanWindow(turns)));
        if (CollUtil.isEmpty(latestFirst)) {
            return List.of();
        }

        Map<String, AgentMessageDO> answers = new HashMap<>();
        for (AgentMessageDO message : latestFirst) {
            if (ROLE_ASSISTANT.equals(message.getRole()) && isUsableAnswer(message)) {
                // 倒序先到的是最新一条，同一提问被重答时以它为准
                answers.putIfAbsent(message.getReplyToMessageId(), message);
            }
        }

        List<ChatMessage> history = new ArrayList<>(turns * 2);
        int paired = 0;
        for (AgentMessageDO question : latestFirst) {
            if (!ROLE_USER.equals(question.getRole()) || StrUtil.isBlank(question.getContent())) {
                continue;
            }
            AgentMessageDO answer = answers.get(question.getId());
            // 落空的有两种：本轮刚落库还没答的提问，以及答案被打断或没生成的作废轮�?            if (answer == null) {
                continue;
            }
            history.add(ChatMessage.assistant(answer.getContent()));
            history.add(ChatMessage.user(question.getContent()));
            if (++paired >= turns) {
                break;
            }
        }
        Collections.reverse(history);
        return history;
    }

    /**
     * 扫描窗口：按 N 对取行数，中途作废一轮就凑不满，宽出一倍留作废余量
     */
    private static int scanWindow(int turns) {
        return turns * 4 + 1;
    }

    /**
     * 半截答案当不得事实，无正文的取消轮次留下的孤立提问也一并作�?     */
    private static boolean isUsableAnswer(AgentMessageDO message) {
        return StrUtil.isNotBlank(message.getReplyToMessageId())
                && StrUtil.isNotBlank(message.getContent())
                && !AgentMessageStatus.INTERRUPTED.name().equals(message.getMessageStatus());
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void delete(String conversationId, String userId) {
        conversationMapper.delete(Wrappers.lambdaQuery(AgentConversationDO.class)
                .eq(AgentConversationDO::getConversationId, conversationId)
                .eq(AgentConversationDO::getUserId, userId));
        messageMapper.delete(Wrappers.lambdaQuery(AgentMessageDO.class)
                .eq(AgentMessageDO::getConversationId, conversationId)
                .eq(AgentMessageDO::getUserId, userId));
        // 会话删了状态留着只会攒僵尸行，一并清掉；同库表随本事务回滚，日后状态换介质得挪到提交后
        agentStateStore.delete(userId, conversationId);
        // 只删表不够：在途流还攥着这个会话的记忆，内存缓存与流本身都得收掉
        afterCommit(() -> releaseRuntimeState(conversationId, userId));
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void deleteBatch(List<String> conversationIds, String userId) {
        if (conversationIds == null || conversationIds.isEmpty()) {
            return;
        }
        // 自调用不过代理，各会话的三步删并入本事务，整批要么全删要么全�?        conversationIds.stream().distinct().forEach(id -> delete(id, userId));
    }

    /**
     * 会话已经不存在，挂在它上面的运行时资源一并收�?     * 停流不只为省 token：流跑到底会把记忆写�?PG、把打断消息插回来，正是「删了又活」的那条�?     */
    private void releaseRuntimeState(String conversationId, String userId) {
        String runningTaskId = runGate.runningTaskId(userId, conversationId);
        if (runningTaskId != null) {
            // 删除路已�?userId 圈定作用域，闸门键本身就是该用户的，无需再比对属主，走系统侧回收
            taskManager.cancel(runningTaskId);
        }
        evictStateCache(userId, conversationId);
    }

    private void evictStateCache(String userId, String conversationId) {
        ReActAgentProvider agentProvider = agentProviderRef.getIfAvailable();
        if (agentProvider != null) {
            agentProvider.evictStateCache(userId, conversationId);
        }
    }

    /**
     * 排到提交之后：删表回滚了记忆却已清空，等于把还在的会话变成失忆会�?     * 无事务上下文时立即执行，免得脱离事务调用悄悄漏掉这一�?     */
    private void afterCommit(Runnable action) {
        if (!TransactionSynchronizationManager.isSynchronizationActive()) {
            action.run();
            return;
        }
        TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
            @Override
            public void afterCommit() {
                action.run();
            }
        });
    }
}
