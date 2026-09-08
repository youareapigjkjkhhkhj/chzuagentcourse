/*
 * Licensed to the Apache Software Foundation (ASF) under one or more
 * contributor license agreements. See the NOTICE file distributed with
 * this work for additional information regarding copyright ownership.
 * The ASF licenses this file to You under the Apache License, Version 2.0.
 */
package com.example.ai.ragent.initializer;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Properties;
import java.util.Set;
import java.util.stream.Stream;

/** Loads and validates one immutable agent-type initialization dataset. */
final class InitializerDataset {

    private final Path agentTypeDir;
    private final List<KnowledgeBaseDefinition> knowledgeBases;
    private final List<IntentDefinition> intents;
    private final List<QuestionDefinition> questions;

    private InitializerDataset(Path agentTypeDir, List<KnowledgeBaseDefinition> knowledgeBases,
                               List<IntentDefinition> intents, List<QuestionDefinition> questions) {
        this.agentTypeDir = agentTypeDir;
        this.knowledgeBases = knowledgeBases;
        this.intents = intents;
        this.questions = questions;
    }

    static InitializerDataset load(Path agentTypeDir) throws IOException {
        Path normalized = agentTypeDir.toAbsolutePath().normalize();
        if (!Files.isDirectory(normalized)) {
            throw new IllegalArgumentException("智能体类型目录不存在: " + normalized);
        }
        List<KnowledgeBaseDefinition> knowledgeBases = loadKnowledgeBases(normalized);
        List<IntentDefinition> intents = loadIntents(normalized, knowledgeBases);
        List<QuestionDefinition> questions = loadQuestions(normalized);
        InitializerDataset dataset = new InitializerDataset(normalized, knowledgeBases, intents, questions);
        dataset.validate();
        return dataset;
    }

    Path agentTypeDir() {
        return agentTypeDir;
    }

    List<KnowledgeBaseDefinition> knowledgeBases() {
        return knowledgeBases;
    }

    List<IntentDefinition> intents() {
        return intents;
    }

    List<QuestionDefinition> questions() {
        return questions;
    }

    int documentCount() throws IOException {
        int count = 0;
        for (KnowledgeBaseDefinition definition : knowledgeBases) {
            count += documents(definition).size();
        }
        return count;
    }

    List<Path> documents(KnowledgeBaseDefinition definition) throws IOException {
        if (!Files.isDirectory(definition.documentsDir())) {
            throw new IllegalArgumentException("知识库文档目录不存在: " + definition.documentsDir());
        }
        try (Stream<Path> paths = Files.walk(definition.documentsDir())) {
            return paths.filter(Files::isRegularFile)
                    .filter(path -> !isHiddenOrSystemFile(definition.documentsDir(), path))
                    .sorted(Comparator.comparing(path -> definition.documentsDir().relativize(path).toString()))
                    .toList();
        }
    }

    void verifyChecksums() throws IOException {
        Path checksumFile = agentTypeDir.resolve("checksums.sha256");
        if (!Files.isRegularFile(checksumFile)) {
            throw new IllegalArgumentException("缺少智能体类型数据校验文�? " + checksumFile);
        }
        int checked = 0;
        for (String rawLine : Files.readAllLines(checksumFile, StandardCharsets.UTF_8)) {
            String line = rawLine.trim();
            if (line.isEmpty() || line.startsWith("#")) {
                continue;
            }
            int separator = line.indexOf("  ");
            if (separator <= 0) {
                throw new IllegalArgumentException("非法 checksum �? " + rawLine);
            }
            String expected = line.substring(0, separator).trim().toLowerCase();
            String relative = line.substring(separator + 2).trim();
            Path target = agentTypeDir.resolve(relative).normalize();
            if (!target.startsWith(agentTypeDir) || !Files.isRegularFile(target)) {
                throw new IllegalArgumentException("checksum 引用了非法文�? " + relative);
            }
            String actual = sha256(target);
            if (!actual.equals(expected)) {
                throw new IllegalStateException("文件 checksum 不一�? " + relative
                        + "，expected=" + expected + "，actual=" + actual);
            }
            checked++;
        }
        if (checked == 0) {
            throw new IllegalArgumentException("checksums.sha256 中没有待校验文件");
        }
    }

    KnowledgeBaseDefinition knowledgeBase(String ref) {
        return knowledgeBases.stream()
                .filter(definition -> definition.ref().equals(ref))
                .findFirst()
                .orElseThrow(() -> new IllegalArgumentException("未知知识库引�? " + ref));
    }

    private void validate() throws IOException {
        Set<String> refs = new HashSet<>();
        Set<String> collections = new HashSet<>();
        for (KnowledgeBaseDefinition definition : knowledgeBases) {
            if (!refs.add(definition.ref())) {
                throw new IllegalArgumentException("知识�?ref 重复: " + definition.ref());
            }
            if (!collections.add(definition.collectionName())) {
                throw new IllegalArgumentException("知识�?collectionName 重复: " + definition.collectionName());
            }
            List<Path> documents = documents(definition);
            if (documents.isEmpty()) {
                throw new IllegalArgumentException("知识库没有文�? " + definition.ref());
            }
            Set<String> filenames = new HashSet<>();
            for (Path document : documents) {
                if (!filenames.add(document.getFileName().toString())) {
                    throw new IllegalArgumentException("同一知识库存在重名文档，HTTP 上传后无法区�? "
                            + definition.ref() + "/" + document.getFileName());
                }
            }
        }

        Set<String> codes = new HashSet<>();
        Map<String, Integer> orderByCode = new HashMap<>();
        for (IntentDefinition intent : intents) {
            if (!codes.add(intent.code())) {
                throw new IllegalArgumentException("意图 code 重复: " + intent.code());
            }
            orderByCode.put(intent.code(), intent.sortOrder());
            if (intent.knowledgeBaseRef() != null) {
                knowledgeBase(intent.knowledgeBaseRef());
            }
        }
        for (IntentDefinition intent : intents) {
            if (intent.parentCode() == null) {
                continue;
            }
            Integer parentOrder = orderByCode.get(intent.parentCode());
            if (parentOrder == null) {
                throw new IllegalArgumentException("意图父节点不存在: " + intent.code() + " -> " + intent.parentCode());
            }
            if (parentOrder >= intent.sortOrder()) {
                throw new IllegalArgumentException("父节点必须排在子节点之前: " + intent.code());
            }
        }

        Set<String> questionRefs = new HashSet<>();
        for (QuestionDefinition question : questions) {
            if (!questionRefs.add(question.ref())) {
                throw new IllegalArgumentException("演示问题 ref 重复: " + question.ref());
            }
        }
    }

    private static List<KnowledgeBaseDefinition> loadKnowledgeBases(Path agentTypeDir) throws IOException {
        Properties properties = InitializerConfig.loadProperties(agentTypeDir.resolve("knowledge-bases.properties"));
        List<String> refs = split(properties.getProperty("knowledge-base.refs"), ",");
        if (refs.isEmpty()) {
            throw new IllegalArgumentException("knowledge-base.refs 不能为空");
        }
        List<KnowledgeBaseDefinition> result = new ArrayList<>();
        for (String ref : refs) {
            String prefix = "knowledge-base." + ref + ".";
            String documents = required(properties, prefix + "documents", "knowledge-bases.properties");
            result.add(new KnowledgeBaseDefinition(
                    ref,
                    required(properties, prefix + "name", "knowledge-bases.properties"),
                    required(properties, prefix + "collection-name", "knowledge-bases.properties"),
                    required(properties, prefix + "embedding-model", "knowledge-bases.properties"),
                    agentTypeDir.resolve(documents).normalize(),
                    trimToNull(properties.getProperty(prefix + "ingestion-spec"))
            ));
        }
        return List.copyOf(result);
    }

    private static List<IntentDefinition> loadIntents(Path agentTypeDir,
                                                       List<KnowledgeBaseDefinition> knowledgeBases) throws IOException {
        Path intentsDir = agentTypeDir.resolve("intents");
        if (!Files.isDirectory(intentsDir)) {
            throw new IllegalArgumentException("意图目录不存�? " + intentsDir);
        }
        Set<String> refs = new HashSet<>();
        knowledgeBases.forEach(definition -> refs.add(definition.ref()));
        List<IntentDefinition> result = new ArrayList<>();
        try (Stream<Path> paths = Files.list(intentsDir)) {
            for (Path file : paths.filter(path -> path.getFileName().toString().endsWith(".properties"))
                    .sorted().toList()) {
                Properties values = InitializerConfig.loadProperties(file);
                String kbRef = trimToNull(values.getProperty("knowledge-base-ref"));
                if (kbRef != null && !refs.contains(kbRef)) {
                    throw new IllegalArgumentException("意图引用了未知知识库 " + kbRef + ": " + file);
                }
                result.add(new IntentDefinition(
                        required(values, "code", file.toString()),
                        required(values, "name", file.toString()),
                        requiredInt(values, "level", file),
                        trimToNull(values.getProperty("parent-code")),
                        requiredInt(values, "kind", file),
                        kbRef,
                        trimToNull(values.getProperty("description")),
                        split(values.getProperty("examples"), "\\|"),
                        trimToNull(values.getProperty("mcp-tool-id")),
                        optionalInt(values, "top-k", file),
                        requiredInt(values, "sort-order", file),
                        optionalBoolean(values, "enabled", true),
                        readOptionalText(agentTypeDir, values.getProperty("prompt-snippet-file")),
                        readOptionalText(agentTypeDir, values.getProperty("prompt-template-file")),
                        readOptionalText(agentTypeDir, values.getProperty("param-prompt-template-file"))
                ));
            }
        }
        result.sort(Comparator.comparingInt(IntentDefinition::sortOrder));
        return List.copyOf(result);
    }

    private static List<QuestionDefinition> loadQuestions(Path agentTypeDir) throws IOException {
        Path file = agentTypeDir.resolve("questions.properties");
        if (!Files.isRegularFile(file)) {
            return List.of();
        }
        Properties properties = InitializerConfig.loadProperties(file);
        List<String> refs = split(properties.getProperty("question.refs"), ",");
        List<QuestionDefinition> result = new ArrayList<>();
        for (String ref : refs) {
            String prefix = "question." + ref + ".";
            result.add(new QuestionDefinition(
                    ref,
                    trimToNull(properties.getProperty(prefix + "title")),
                    trimToNull(properties.getProperty(prefix + "description")),
                    required(properties, prefix + "text", "questions.properties"),
                    split(properties.getProperty(prefix + "follow-ups"), "\\|")
            ));
        }
        return List.copyOf(result);
    }

    private static String readOptionalText(Path agentTypeDir, String relative) throws IOException {
        String value = trimToNull(relative);
        if (value == null) {
            return null;
        }
        Path file = agentTypeDir.resolve(value).normalize();
        if (!file.startsWith(agentTypeDir) || !Files.isRegularFile(file)) {
            throw new IllegalArgumentException("Prompt 文件不存在或越出智能体类型目�? " + relative);
        }
        return Files.readString(file, StandardCharsets.UTF_8);
    }

    private static boolean isHiddenOrSystemFile(Path root, Path path) {
        Path relative = root.relativize(path);
        for (Path part : relative) {
            String name = part.toString();
            if (name.startsWith(".") || ".DS_Store".equalsIgnoreCase(name)) {
                return true;
            }
        }
        return false;
    }

    private static String sha256(Path file) throws IOException {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            try (var input = Files.newInputStream(file)) {
                byte[] buffer = new byte[8192];
                int read;
                while ((read = input.read(buffer)) >= 0) {
                    if (read > 0) {
                        digest.update(buffer, 0, read);
                    }
                }
            }
            return HexFormat.of().formatHex(digest.digest());
        } catch (NoSuchAlgorithmException ex) {
            throw new IllegalStateException("JDK 不支�?SHA-256", ex);
        }
    }

    private static String required(Properties properties, String key, String source) {
        String value = trimToNull(properties.getProperty(key));
        if (value == null) {
            throw new IllegalArgumentException("缺少配置�?" + key + "，文�? " + source);
        }
        return value;
    }

    private static int requiredInt(Properties properties, String key, Path source) {
        String value = required(properties, key, source.toString());
        try {
            return Integer.parseInt(value);
        } catch (NumberFormatException ex) {
            throw new IllegalArgumentException("配置项不是整�?" + key + "，文�? " + source, ex);
        }
    }

    private static Integer optionalInt(Properties properties, String key, Path source) {
        String value = trimToNull(properties.getProperty(key));
        if (value == null) {
            return null;
        }
        try {
            return Integer.valueOf(value);
        } catch (NumberFormatException ex) {
            throw new IllegalArgumentException("配置项不是整�?" + key + "，文�? " + source, ex);
        }
    }

    private static boolean optionalBoolean(Properties properties, String key, boolean defaultValue) {
        String value = trimToNull(properties.getProperty(key));
        return value == null ? defaultValue : Boolean.parseBoolean(value);
    }

    private static List<String> split(String value, String regex) {
        if (value == null || value.isBlank()) {
            return List.of();
        }
        List<String> result = new ArrayList<>();
        for (String item : value.split(regex)) {
            if (!item.isBlank()) {
                result.add(item.trim());
            }
        }
        return List.copyOf(result);
    }

    private static String trimToNull(String value) {
        return value == null || value.trim().isEmpty() ? null : value.trim();
    }

    record KnowledgeBaseDefinition(String ref, String name, String collectionName, String embeddingModel,
                                   Path documentsDir, String ingestionSpec) {
    }

    record IntentDefinition(String code, String name, int level, String parentCode, int kind,
                            String knowledgeBaseRef, String description, List<String> examples,
                            String mcpToolId, Integer topK, int sortOrder, boolean enabled,
                            String promptSnippet, String promptTemplate, String paramPromptTemplate) {
    }

    record QuestionDefinition(String ref, String title, String description, String text, List<String> followUps) {

        /**
         * 一次会话内按顺序发出的全部提问，首轮之后的都是追问
         */
        List<String> turns() {
            List<String> turns = new ArrayList<>();
            turns.add(text);
            turns.addAll(followUps);
            return List.copyOf(turns);
        }
    }
}
