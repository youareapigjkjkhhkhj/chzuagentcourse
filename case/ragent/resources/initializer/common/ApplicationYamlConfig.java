/*
 * Licensed to the Apache Software Foundation (ASF) under one or more
 * contributor license agreements. See the NOTICE file distributed with
 * this work for additional information regarding copyright ownership.
 * The ASF licenses this file to You under the Apache License, Version 2.0.
 */
package com.example.ai.ragent.initializer;

import java.io.IOException;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Properties;

/** Reads the small set of Spring Boot YAML values required by the standalone CLI tools. */
final class ApplicationYamlConfig {

    private ApplicationYamlConfig() {
    }

    static Properties load(Path file) throws IOException {
        if (!Files.isRegularFile(file)) {
            throw new IllegalArgumentException("RagentAI application.yaml 不存�? " + file);
        }
        Map<String, String> yaml = readScalarValues(file);
        Properties result = new Properties();

        String port = value(yaml, "server.port", "8080");
        String contextPath = value(yaml, "server.servlet.context-path", "");
        if (!contextPath.isEmpty() && !contextPath.startsWith("/")) {
            contextPath = "/" + contextPath;
        }
        while (contextPath.endsWith("/") && contextPath.length() > 1) {
            contextPath = contextPath.substring(0, contextPath.length() - 1);
        }
        String address = value(yaml, "server.address", "127.0.0.1");
        if ("0.0.0.0".equals(address) || "::".equals(address) || "[::]".equals(address)) {
            address = "127.0.0.1";
        }
        String scheme = Boolean.parseBoolean(value(yaml, "server.ssl.enabled", "false")) ? "https" : "http";
        result.setProperty("server.base-url", scheme + "://" + address + ":" + port + contextPath);

        applyPostgres(yaml, file, result);
        result.setProperty("redis.host", required(yaml, "spring.data.redis.host", file));
        result.setProperty("redis.port", value(yaml, "spring.data.redis.port", "6379"));
        result.setProperty("redis.password", value(yaml, "spring.data.redis.password", ""));
        result.setProperty("redis.database", value(yaml, "spring.data.redis.database", "0"));

        result.setProperty("execution.expected-vector-type", value(yaml, "rag.vector.type", ""));
        result.setProperty("execution.expected-storage-type", value(yaml, "rag.storage.type", ""));
        result.setProperty("execution.engine-type", value(yaml, "ragent.engine.type", ""));

        // 记忆回归台要在报告里同时给出「服务端在用的阈值」和「本次实测量」，阈值只能来自这一�?yaml
        // 四道门已收敛成窗口的固定比例，这里只搬窗口本身；派生用的比例�?AgentMemoryRegressionMain 里另有一份手抄副�?        result.setProperty("agent.memory.context-window-chars",
                value(yaml, "agent.memory.context-window-chars", "0"));
        result.setProperty("agent.memory.summary-enabled",
                value(yaml, "agent.memory.summary-enabled", "true"));
        result.setProperty("agent.memory.long-term-enabled",
                value(yaml, "agent.memory.long-term-enabled", "true"));
        return result;
    }

    private static void applyPostgres(Map<String, String> yaml, Path file, Properties result) {
        String jdbcUrl = required(yaml, "spring.datasource.url", file);
        if (!jdbcUrl.startsWith("jdbc:")) {
            throw new IllegalArgumentException("spring.datasource.url 不是 JDBC URL: " + jdbcUrl);
        }
        URI uri;
        try {
            uri = URI.create(jdbcUrl.substring("jdbc:".length()));
        } catch (IllegalArgumentException ex) {
            throw new IllegalArgumentException("spring.datasource.url 格式错误: " + jdbcUrl, ex);
        }
        if (!"postgresql".equalsIgnoreCase(uri.getScheme()) || uri.getHost() == null) {
            throw new IllegalArgumentException("初始化器仅支�?PostgreSQL JDBC URL: " + jdbcUrl);
        }
        String database = uri.getPath();
        if (database == null || database.length() <= 1) {
            throw new IllegalArgumentException("spring.datasource.url 缺少数据库名: " + jdbcUrl);
        }
        result.setProperty("database.jdbc-url", jdbcUrl);
        result.setProperty("database.host", uri.getHost());
        result.setProperty("database.port", String.valueOf(uri.getPort() < 0 ? 5432 : uri.getPort()));
        result.setProperty("database.name", database.substring(1));
        result.setProperty("database.username", required(yaml, "spring.datasource.username", file));
        result.setProperty("database.password", value(yaml, "spring.datasource.password", ""));
    }

    private static String required(Map<String, String> values, String key, Path file) {
        String result = value(values, key, null);
        if (result == null || result.isBlank()) {
            throw new IllegalArgumentException("application.yaml 缺少配置�?" + key + "，文�? " + file);
        }
        return result;
    }

    private static String value(Map<String, String> values, String key, String defaultValue) {
        String value = values.get(key);
        if (value == null) {
            return defaultValue;
        }
        return InitializerConfig.expandPlaceholders(value).trim();
    }

    private static Map<String, String> readScalarValues(Path file) throws IOException {
        Map<String, String> result = new LinkedHashMap<>();
        List<YamlLevel> levels = new ArrayList<>();
        int blockScalarIndent = -1;
        for (String rawLine : Files.readAllLines(file, StandardCharsets.UTF_8)) {
            if (rawLine.isBlank()) {
                continue;
            }
            int indent = leadingSpaces(rawLine);
            String content = rawLine.substring(indent).trim();
            if (blockScalarIndent >= 0) {
                if (indent > blockScalarIndent) {
                    continue;
                }
                blockScalarIndent = -1;
            }
            if (content.isEmpty() || content.startsWith("#") || content.startsWith("- ")) {
                continue;
            }
            while (!levels.isEmpty() && levels.get(levels.size() - 1).indent() >= indent) {
                levels.remove(levels.size() - 1);
            }
            int separator = content.indexOf(':');
            if (separator <= 0) {
                continue;
            }
            String key = content.substring(0, separator).trim();
            String rawValue = stripInlineComment(content.substring(separator + 1)).trim();
            if (rawValue.isEmpty()) {
                levels.add(new YamlLevel(indent, key));
                continue;
            }
            if (rawValue.matches("[|>][+-]?")) {
                blockScalarIndent = indent;
                continue;
            }
            StringBuilder dottedKey = new StringBuilder();
            for (YamlLevel level : levels) {
                dottedKey.append(level.key()).append('.');
            }
            dottedKey.append(key);
            result.put(dottedKey.toString(), unquote(rawValue));
        }
        return result;
    }

    private static int leadingSpaces(String value) {
        int count = 0;
        while (count < value.length() && value.charAt(count) == ' ') {
            count++;
        }
        return count;
    }

    private static String stripInlineComment(String value) {
        boolean singleQuoted = false;
        boolean doubleQuoted = false;
        for (int index = 0; index < value.length(); index++) {
            char current = value.charAt(index);
            if (current == '\'' && !doubleQuoted) {
                singleQuoted = !singleQuoted;
            } else if (current == '"' && !singleQuoted) {
                doubleQuoted = !doubleQuoted;
            } else if (current == '#' && !singleQuoted && !doubleQuoted
                    && (index == 0 || Character.isWhitespace(value.charAt(index - 1)))) {
                return value.substring(0, index);
            }
        }
        return value;
    }

    private static String unquote(String value) {
        if (value.length() >= 2) {
            char first = value.charAt(0);
            char last = value.charAt(value.length() - 1);
            if ((first == '\'' && last == '\'') || (first == '"' && last == '"')) {
                return value.substring(1, value.length() - 1);
            }
        }
        return value;
    }

    private record YamlLevel(int indent, String key) {
    }
}
