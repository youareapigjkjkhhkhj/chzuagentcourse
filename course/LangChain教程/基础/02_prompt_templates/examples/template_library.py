"""
可复用的提示词模板库
====================

这个文件包含常用的、经过优化的提示词模板
可以直接在项目中导入使用

使用方法：
    from examples.template_library import TemplateLibrary

    messages = TemplateLibrary.TRANSLATOR.format_messages(
        source_lang="英语",
        target_lang="中文",
        text="Hello World"
    )
"""

from langchain_core.prompts import ChatPromptTemplate


class TemplateLibrary:
    """可复用的提示词模板库"""

    # ========================================================================
    # 翻译类模板
    # ========================================================================

    TRANSLATOR = ChatPromptTemplate.from_messages([
        ("system",
         "你是一个专业的翻译专家，精通{source_lang}和{target_lang}。\n"
         "翻译要求：\n"
         "1. 准确传达原文意思\n"
         "2. 符合目标语言习惯\n"
         "3. 保持原文风格和语气"),
        ("user", "请将以下{source_lang}文本翻译成{target_lang}：\n\n{text}")
    ])
    """
    翻译模板

    变量：
        source_lang: 源语言（如：英语、中文）
        target_lang: 目标语言
        text: 要翻译的文本

    示例：
        messages = TRANSLATOR.format_messages(
            source_lang="英语",
            target_lang="中文",
            text="Hello, how are you?"
        )
    """

    # ========================================================================
    # 编程类模板
    # ========================================================================

    CODE_GENERATOR = ChatPromptTemplate.from_messages([
        ("system",
         "你是一个经验丰富的{language}开发者。\n"
         "代码要求：\n"
         "1. 遵循{language}最佳实践\n"
         "2. 添加必要的注释\n"
         "3. 代码简洁、可读性强"),
        ("user",
         "请用{language}编写代码实现以下功能：\n\n{description}\n\n"
         "附加要求：{requirements}")
    ])
    """代码生成模板"""

    CODE_REVIEWER = ChatPromptTemplate.from_messages([
        ("system",
         "你是一个资深的{language}代码审查专家。\n"
         "审查重点：{focus}\n"
         "请提供：\n"
         "1. 代码质量评分（1-10分）\n"
         "2. 主要问题和改进建议\n"
         "3. 优化后的代码（如有必要）"),
        ("user",
         "请审查以下{language}代码：\n\n"
         "```{language}\n{code}\n```")
    ])
    """代码审查模板"""

    CODE_EXPLAINER = ChatPromptTemplate.from_messages([
        ("system",
         "你是一个{language}编程导师，擅长用{style}的方式解释代码。"),
        ("user",
         "请解释以下{language}代码的功能和实现原理：\n\n"
         "```{language}\n{code}\n```")
    ])
    """代码解释模板"""

    DEBUG_HELPER = ChatPromptTemplate.from_messages([
        ("system",
         "你是一个调试专家，擅长分析和解决{language}代码问题。"),
        ("user",
         "我的{language}代码遇到了以下错误：\n\n"
         "错误信息：\n{error_message}\n\n"
         "代码：\n```{language}\n{code}\n```\n\n"
         "请帮我：\n1. 分析错误原因\n2. 提供解决方案\n3. 给出修正后的代码")
    ])
    """调试助手模板"""

    # ========================================================================
    # 内容创作类模板
    # ========================================================================

    SUMMARIZER = ChatPromptTemplate.from_messages([
        ("system",
         "你是一个内容摘要专家，擅长提取关键信息。\n"
         "摘要要求：\n"
         "1. 保留最重要的信息\n"
         "2. 简洁明了\n"
         "3. 条理清晰"),
        ("user",
         "请将以下内容总结为{num_points}个要点：\n\n{content}")
    ])
    """内容摘要模板"""

    ARTICLE_WRITER = ChatPromptTemplate.from_messages([
        ("system",
         "你是一个专业的{field}领域作家。\n"
         "写作风格：{style}\n"
         "目标读者：{audience}"),
        ("user",
         "请写一篇关于{topic}的文章。\n"
         "要求：\n"
         "1. 字数：{word_count}字左右\n"
         "2. 结构：{structure}\n"
         "3. 重点：{focus}")
    ])
    """文章写作模板"""

    EMAIL_WRITER = ChatPromptTemplate.from_messages([
        ("system",
         "你是一个专业的商务邮件撰写专家。\n"
         "邮件风格：{tone}\n"
         "收件人类型：{recipient_type}"),
        ("user",
         "请帮我写一封邮件：\n"
         "目的：{purpose}\n"
         "关键内容：{key_points}")
    ])
    """邮件撰写模板"""

    # ========================================================================
    # 教育类模板
    # ========================================================================

    TUTOR = ChatPromptTemplate.from_messages([
        ("system",
         "你是一个{subject}导师。\n"
         "学生水平：{level}\n"
         "教学风格：{teaching_style}"),
        ("user", "{question}")
    ])
    """教学辅导模板"""

    QUIZ_GENERATOR = ChatPromptTemplate.from_messages([
        ("system",
         "你是一个{subject}测验题目生成专家。\n"
         "难度级别：{difficulty}\n"
         "题目类型：{question_type}"),
        ("user",
         "请生成{num}道关于{topic}的{question_type}题目。\n"
         "要求：\n"
         "1. 覆盖关键知识点\n"
         "2. 难度适中\n"
         "3. 提供标准答案")
    ])
    """测验生成模板"""

    # ========================================================================
    # 商务类模板
    # ========================================================================

    PRODUCT_DESCRIPTION = ChatPromptTemplate.from_messages([
        ("system",
         "你是一个专业的产品文案撰写专家。\n"
         "写作风格：{style}\n"
         "目标客户：{target_audience}"),
        ("user",
         "请为以下产品撰写描述：\n"
         "产品名称：{product_name}\n"
         "核心卖点：{key_features}\n"
         "字数要求：{word_count}字")
    ])
    """产品描述模板"""

    MARKET_ANALYSIS = ChatPromptTemplate.from_messages([
        ("system",
         "你是一个{industry}行业的市场分析专家。\n"
         "分析维度：{dimensions}"),
        ("user",
         "请分析{topic}的市场情况，重点关注：\n{focus_areas}")
    ])
    """市场分析模板"""

    # ========================================================================
    # 客户服务类模板
    # ========================================================================

    CUSTOMER_SUPPORT = ChatPromptTemplate.from_messages([
        ("system",
         "你是{company}的客服专员。\n"
         "服务态度：友好、专业、耐心\n"
         "回复风格：{tone}\n"
         "可用操作：{available_actions}"),
        ("user", "{customer_message}")
    ])
    """客户服务模板"""

    FAQ_RESPONDER = ChatPromptTemplate.from_messages([
        ("system",
         "你是一个FAQ问答专家。\n"
         "知识库：{knowledge_base}\n"
         "如果问题不在知识库中，请礼貌地说明无法回答。"),
        ("user", "{question}")
    ])
    """FAQ回答模板"""

    # ========================================================================
    # 数据分析类模板
    # ========================================================================

    DATA_ANALYZER = ChatPromptTemplate.from_messages([
        ("system",
         "你是一个数据分析专家，擅长{analysis_type}分析。\n"
         "分析工具：{tools}"),
        ("user",
         "请分析以下数据：\n{data}\n\n"
         "分析要求：\n{requirements}")
    ])
    """数据分析模板"""

    REPORT_GENERATOR = ChatPromptTemplate.from_messages([
        ("system",
         "你是一个{report_type}报告撰写专家。\n"
         "报告受众：{audience}"),
        ("user",
         "请基于以下信息生成报告：\n{information}\n\n"
         "报告结构：{structure}")
    ])
    """报告生成模板"""


# ============================================================================
# 使用示例
# ============================================================================

if __name__ == "__main__":
    """测试模板库"""

    print("="*70)
    print(" 提示词模板库示例")
    print("="*70)

    # 示例 1：翻译模板
    print("\n【示例 1：翻译模板】")
    messages = TemplateLibrary.TRANSLATOR.format_messages(
        source_lang="英语",
        target_lang="中文",
        text="Hello, how are you today?"
    )
    print("生成的消息：")
    for msg in messages:
        print(f"  {msg.type}: {msg.content[:50]}...")

    # 示例 2：代码生成模板
    print("\n【示例 2：代码生成模板】")
    messages = TemplateLibrary.CODE_GENERATOR.format_messages(
        language="Python",
        description="计算斐波那契数列的第n项",
        requirements="使用递归实现，添加类型注解"
    )
    print("生成的消息：")
    for msg in messages:
        print(f"  {msg.type}: {msg.content[:80]}...")

    # 示例 3：摘要模板
    print("\n【示例 3：摘要模板】")
    messages = TemplateLibrary.SUMMARIZER.format_messages(
        num_points=3,
        content="Python 是一种高级编程语言，以其简洁的语法和强大的功能而闻名..."
    )
    print("生成的消息：")
    for msg in messages:
        print(f"  {msg.type}: {msg.content[:80]}...")

    print("\n" + "="*70)
    print(" 提示：在实际项目中，直接导入使用这些模板")
    print(" from examples.template_library import TemplateLibrary")
    print("="*70)
