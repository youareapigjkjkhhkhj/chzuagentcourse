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

package com.example.ai.ragent.rag.core.intent;

import com.example.ai.ragent.infra.chat.LLMService;
import com.example.ai.ragent.rag.core.prompt.PromptTemplateLoader;
import com.example.ai.ragent.rag.dao.entity.IntentNodeDO;
import com.example.ai.ragent.rag.dao.mapper.IntentNodeMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyMap;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class DefaultIntentClassifierTest {

    @Mock
    private LLMService llmService;

    @Mock
    private IntentNodeMapper intentNodeMapper;

    @Mock
    private PromptTemplateLoader promptTemplateLoader;

    @Mock
    private IntentTreeCacheManager intentTreeCacheManager;

    private DefaultIntentClassifier classifier;

    @BeforeEach
    void setUp() {
        classifier = new DefaultIntentClassifier(
                llmService,
                intentNodeMapper,
                promptTemplateLoader,
                intentTreeCacheManager
        );
    }

    @Test
    void skipsLlmWhenIntentTreeIsEmpty() {
        when(intentTreeCacheManager.getIntentTreeFromCache()).thenReturn(List.of());
        when(intentNodeMapper.selectList(any())).thenReturn(List.of());

        List<NodeScore> scores = classifier.classifyTargets("How do I apply for leave?");

        assertTrue(scores.isEmpty());
        verifyNoInteractions(llmService, promptTemplateLoader);
    }

    @Test
    @SuppressWarnings("unchecked")
    void unwrapsJsonExamplesBeforeRenderingPrompt() {
        IntentNodeDO node = IntentNodeDO.builder()
                .intentCode("sys-feedback")
                .name("评价反馈")
                .level(1)
                .kind(1)
                .description("用户对上一轮回答做出评�?)
                .examples("[\"回答得不错\",\"你答错了\"]")
                .build();
        when(intentTreeCacheManager.getIntentTreeFromCache()).thenReturn(null);
        when(intentNodeMapper.selectList(any())).thenReturn(List.of(node));
        when(promptTemplateLoader.render(anyString(), anyMap())).thenReturn("system-prompt");
        when(llmService.chat(any())).thenReturn("[]");

        classifier.classifyTargets("回答得不�?);

        ArgumentCaptor<Map<String, String>> captor = ArgumentCaptor.forClass(Map.class);
        verify(promptTemplateLoader).render(anyString(), captor.capture());
        assertTrue(captor.getValue().get("intent_list").contains("examples=回答得不�?/ 你答错了"));
    }
}
