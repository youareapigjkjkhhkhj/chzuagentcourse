SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '120s';

-- Explicit allowlist. Do not add CASCADE: new relationships must be reviewed deliberately.
TRUNCATE TABLE
    t_message_feedback,
    t_conversation_summary,
    t_message,
    t_conversation,
    t_agent_state,
    t_agent_message,
    t_agent_conversation,
    t_rag_trace_node,
    t_rag_trace_run,
    t_ingestion_task_node,
    t_ingestion_task,
    t_ingestion_pipeline_node,
    t_ingestion_pipeline,
    t_knowledge_document_schedule_exec,
    t_knowledge_document_schedule,
    t_knowledge_document_chunk_log,
    t_knowledge_chunk,
    t_knowledge_document,
    t_knowledge_vector,
    t_intent_node,
    t_query_term_mapping,
    t_sample_question,
    t_knowledge_base,
    t_biz_change_log
RESTART IDENTITY;
