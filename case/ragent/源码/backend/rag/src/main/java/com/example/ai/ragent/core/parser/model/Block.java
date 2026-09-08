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

package com.example.ai.ragent.core.parser.model;

/**
 * 结构化解析产物的统一基类：解析器输出�?ChunkerNode 之间的内存中间表示，仅存活于解析阶段
 * <p>
 * sealed 保证编译期穷举，新增 Block 类型时所�?switch 必须显式处理；Block 只描述内容本身，章节路径�? * HeadingHandler 在遍历时累积�?ChunkContext，入库的 markdown 展示文本由各 chunker 在切分阶段渲染；
 * 不带 Jackson 多态注解，全程无序列化出入�? */
public sealed interface Block
        permits HeadingBlock, ParagraphBlock, TableBlock, HtmlTableBlock, ImageBlock, CodeBlock, ListBlock {

    /**
     * 来源信息：文件、页�?/ sheet、bbox / 单元格范�?     */
    Provenance provenance();
}
