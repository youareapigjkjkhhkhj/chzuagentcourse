/*
 * Licensed to the Apache Software Foundation (ASF) under one or more
 * contributor license agreements. See the NOTICE file distributed with
 * this work for additional information regarding copyright ownership.
 * The ASF licenses this file to You under the Apache License, Version 2.0.
 */
package com.example.ai.ragent.initializer;

import java.io.IOException;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

/** Runtime state shared by all actions in one initializer invocation. */
final class InitializerContext implements AutoCloseable {

    private static final Set<String> FLAG_ARGUMENTS = Set.of("dry-run", "skip-warmup");

    private final Path agentTypeDir;
    private final InitializerConfig config;
    private final InitializerDataset dataset;
    private final RagentHttpClient http;
    private final JdbcClient jdbc;
    private final RedisRespClient redis;
    private final boolean dryRun;
    private final boolean skipWarmup;
    private final String confirmation;
    private final String runId = UUID.randomUUID().toString();
    private final Map<String, KnowledgeBaseRuntime> knowledgeBases = new HashMap<>();
    private RagentHttpClient.LoginSession loginSession;

    private InitializerContext(Path agentTypeDir, InitializerConfig config, InitializerDataset dataset,
                               boolean dryRun, boolean skipWarmup, String confirmation) {
        this.agentTypeDir = agentTypeDir;
        this.config = config;
        this.dataset = dataset;
        this.dryRun = dryRun;
        this.skipWarmup = skipWarmup;
        this.confirmation = confirmation;
        this.http = new RagentHttpClient(config);
        this.jdbc = new JdbcClient(config);
        this.redis = new RedisRespClient(config);
    }

    static InitializerContext load(String[] args) throws Exception {
        Map<String, String> arguments = parseArguments(args);
        String agentTypeDirValue = arguments.get("agent-type-dir");
        if (agentTypeDirValue == null || agentTypeDirValue.isBlank()) {
            throw new IllegalArgumentException("必须传入 --agent-type-dir <智能体类型目�?");
        }
        Path agentTypeDir = Path.of(agentTypeDirValue).toAbsolutePath().normalize();
        Path configFile = arguments.containsKey("config")
                ? Path.of(arguments.get("config")).toAbsolutePath().normalize()
                : agentTypeDir.resolve("initializer.properties");
        InitializerConfig config = InitializerConfig.load(configFile);
        InitializerDataset dataset = InitializerDataset.load(agentTypeDir);
        return new InitializerContext(agentTypeDir, config, dataset,
                arguments.containsKey("dry-run"), arguments.containsKey("skip-warmup"), arguments.get("confirm"));
    }

    void loginAsAdmin() throws Exception {
        loginSession = http.login(config.require("auth.username"), config.require("auth.password"));
        if (!"admin".equalsIgnoreCase(loginSession.role())) {
            throw new IllegalStateException("初始化账号不�?Admin，role=" + loginSession.role());
        }
    }

    void requireConfirmation() {
        String expected = config.require("cleanup.confirmation");
        if (!expected.equals(confirmation)) {
            throw new IllegalArgumentException("这是破坏性操作，请增加参�?--confirm " + expected);
        }
    }

    Path agentTypeDir() {
        return agentTypeDir;
    }

    InitializerConfig config() {
        return config;
    }

    InitializerDataset dataset() {
        return dataset;
    }

    RagentHttpClient http() {
        return http;
    }

    JdbcClient jdbc() {
        return jdbc;
    }

    RedisRespClient redis() {
        return redis;
    }

    boolean dryRun() {
        return dryRun;
    }

    boolean skipWarmup() {
        return skipWarmup;
    }

    String runId() {
        return runId;
    }

    Map<String, KnowledgeBaseRuntime> knowledgeBases() {
        return knowledgeBases;
    }

    private static Map<String, String> parseArguments(String[] args) {
        Map<String, String> result = new HashMap<>();
        for (int index = 0; index < args.length; index++) {
            String argument = args[index];
            if (!argument.startsWith("--")) {
                throw new IllegalArgumentException("无法识别的参�? " + argument);
            }
            String key = argument.substring(2);
            int equals = key.indexOf('=');
            if (equals >= 0) {
                result.put(key.substring(0, equals), key.substring(equals + 1));
                continue;
            }
            if (FLAG_ARGUMENTS.contains(key)) {
                result.put(key, "true");
                continue;
            }
            if (index + 1 >= args.length || args[index + 1].startsWith("--")) {
                throw new IllegalArgumentException("参数缺少�? --" + key);
            }
            result.put(key, args[++index]);
        }
        return result;
    }

    @Override
    public void close() throws IOException {
        IOException failure = null;
        try {
            http.close();
        } catch (RuntimeException ex) {
            failure = new IOException("退�?Ragent 登录失败", ex);
        }
        try {
            jdbc.close();
        } catch (IOException ex) {
            if (failure == null) {
                failure = ex;
            } else {
                failure.addSuppressed(ex);
            }
        }
        try {
            redis.close();
        } catch (IOException ex) {
            if (failure == null) {
                failure = ex;
            } else {
                failure.addSuppressed(ex);
            }
        }
        if (failure != null) {
            throw failure;
        }
    }

    record KnowledgeBaseRuntime(String id, String collectionName, String name) {
    }
}
