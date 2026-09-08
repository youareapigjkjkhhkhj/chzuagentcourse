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

package com.example.ai.ragent.rag.config.validation;

import java.util.ArrayList;
import java.util.List;
import java.util.function.Function;
import java.util.function.Predicate;

/**
 * 检索通道「后端装�?vs 通道启用」一致性校验（纯逻辑，不依赖 Spring，便于单测）
 * <p>
 * 两层完全正交�? * <ul>
 *   <li>后端装配 {@code rag.{keyword,graph}.type}：决定实�?bean 是否�?{@code @ConditionalOnProperty} 注册�? *       {@code none}（或非法值）时通道类根本不进容�?/li>
 *   <li>通道启用 {@code rag.search.channels.*.enabled}：仅在通道 bean 存在后，检索期才被 {@code isEnabled()} 读取</li>
 * </ul>
 * 有效参与 = 后端已装�?AND 通道已启用。故 {@code type=none �?enabled=true} 是哑标志�? * 用户以为开了该路检索，实际那个通道类都没注册，{@code enabled=true} 无人读取——本校验器专抓这种单向矛�? * <p>
 * 单向性刻意为之：反过来的 {@code type=lightrag �?enabled=false} 是合法的（后端仅供可视化 / 只读，不参与召回），不报
 */
public final class RetrievalChannelConfigValidator {

    private RetrievalChannelConfigValidator() {
    }

    /**
     * 一条「后端未装配却开了检索通道」的矛盾
     *
     * @param channelLabel 通道中文名，用于报错
     * @param typeKey      后端类型配置键，�?rag.keyword.type
     * @param actualType   该键的实际取值，可能为空
     * @param requiredType 装配该后端所需的取值，�?es / lightrag
     * @param enabledKey   通道启用配置键，�?rag.search.channels.keyword.enabled
     * @param enableHint   若选择启用该检索，除设 type 外的补充提示
     */
    public record Violation(String channelLabel,
                            String typeKey,
                            String actualType,
                            String requiredType,
                            String enabledKey,
                            String enableHint) {
    }

    /**
     * 待校验的通道规格：新增一路检索只需�?{@link #SPECS} 里加一�?     */
    private record ChannelSpec(String label,
                               String typeKey,
                               String requiredType,
                               String enabledKey,
                               String enableHint) {
    }

    private static final List<ChannelSpec> SPECS = List.of(
            new ChannelSpec("关键词检�?, "rag.keyword.type", "es",
                    "rag.search.channels.keyword.enabled", "并配�?rag.keyword.es.*"),
            new ChannelSpec("图谱检�?, "rag.graph.type", "lightrag",
                    "rag.search.channels.graph.enabled", "并确�?LightRAG 服务可达（rag.graph.lightrag.base-url�?)
    );

    /**
     * 校验所有通道，一次性收集全部违规（不撞到第一条就停，便于用户一次改完）
     *
     * @param typeReader    读取 type 键的实际值（不存在返�?null�?     * @param enabledReader 读取通道启用开关（不存在按 false�?     * @return 违规列表，空表示配置自洽
     */
    public static List<Violation> validate(Function<String, String> typeReader,
                                           Predicate<String> enabledReader) {
        List<Violation> violations = new ArrayList<>();
        for (ChannelSpec spec : SPECS) {
            String actualType = typeReader.apply(spec.typeKey());
            // 后端未装配：type 缺省 / 空白 / 非所需值（大小写不敏感，与 @ConditionalOnProperty 判定对齐�?            boolean backendOff = actualType == null
                    || actualType.isBlank()
                    || !actualType.trim().equalsIgnoreCase(spec.requiredType());
            if (backendOff && enabledReader.test(spec.enabledKey())) {
                violations.add(new Violation(spec.label(), spec.typeKey(),
                        actualType == null ? "" : actualType, spec.requiredType(),
                        spec.enabledKey(), spec.enableHint()));
            }
        }
        return violations;
    }
}
