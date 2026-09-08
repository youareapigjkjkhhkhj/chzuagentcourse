"""
模块 17：多 Agent 协作
学习如何创建多个专业化 Agent 并让它们协作
"""

import os
from typing import TypedDict, Annotated, Literal, List
from dotenv import load_dotenv

from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.tools import tool

# 加载环境变量
load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not GROQ_API_KEY or GROQ_API_KEY == "your_groq_api_key_here":
    raise ValueError(
        "\n请先在 .env 文件中设置有效的 GROQ_API_KEY\n"
        "访问 https://console.groq.com/keys 获取免费密钥"
    )

# 初始化模型
model = init_chat_model("groq:llama-3.3-70b-versatile", api_key=GROQ_API_KEY)

# ============================================================
# 定义工具
# ============================================================

@tool
def search_web(query: str) -> str:
    """搜索网络获取最新信息"""
    # 模拟搜索结果
    mock_results = {
        "人工智能": "人工智能(AI)是计算机科学的一个分支，致力于创建能够执行通常需要人类智能的任务的系统。主要领域包括机器学习、深度学习、自然语言处理等。",
        "机器学习": "机器学习是AI的子领域，通过算法让计算机从数据中学习。常见方法包括监督学习、无监督学习和强化学习。",
        "default": f"找到关于'{query}'的相关信息：这是一个重要的技术领域，正在快速发展中。"
    }
    for key in mock_results:
        if key in query:
            return mock_results[key]
    return mock_results["default"]

@tool
def check_grammar(text: str) -> str:
    """检查文本的语法和表达"""
    # 模拟语法检查
    return f"语法检查完成。文本长度：{len(text)}字符。建议：表达清晰，结构合理。"

# ============================================================
# 示例 1：监督者模式
# ============================================================

def supervisor_pattern():
    """
    监督者模式：由一个 Supervisor 协调多个专业 Agent
    """
    print("\n" + "=" * 60)
    print("示例 1：监督者模式 - 内容创作团队")
    print("=" * 60)

    # 定义状态
    class TeamState(TypedDict):
        task: str
        messages: Annotated[list, add_messages]
        research_result: str
        draft: str
        final_content: str
        next_agent: str

    # 初始化模型
    
    # 监督者节点
    def supervisor(state: TeamState) -> dict:
        """监督者：决定下一步由哪个 Agent 处理"""
        print("  [监督者] 分析任务状态...")
        
        # 决策逻辑
        if not state.get("research_result"):
            next_agent = "researcher"
            print("  [监督者] 决定：需要先研究 -> 分配给研究员")
        elif not state.get("draft"):
            next_agent = "writer"
            print("  [监督者] 决定：有研究结果，需要写作 -> 分配给作家")
        elif not state.get("final_content"):
            next_agent = "editor"
            print("  [监督者] 决定：有初稿，需要编辑 -> 分配给编辑")
        else:
            next_agent = "complete"
            print("  [监督者] 决定：任务完成")
        
        return {"next_agent": next_agent}

    # 研究员 Agent
    def researcher(state: TeamState) -> dict:
        """研究员：收集和整理信息"""
        print("  [研究员] 开始研究任务...")
        
        # 使用搜索工具
        search_result = search_web.invoke({"query": state["task"]})
        
        # 使用 LLM 整理信息
        messages = [
            SystemMessage(content="你是一个研究员，请根据搜索结果整理出关键信息要点。用中文回复。"),
            HumanMessage(content=f"任务：{state['task']}\n\n搜索结果：{search_result}")
        ]
        response = model.invoke(messages)
        
        print(f"  [研究员] 研究完成，整理了 {len(response.content)} 字的资料")
        
        return {
            "research_result": response.content,
            "messages": [AIMessage(content=f"[研究员] {response.content}")]
        }

    # 作家 Agent
    def writer(state: TeamState) -> dict:
        """作家：根据研究结果撰写内容"""
        print("  [作家] 开始撰写内容...")
        
        messages = [
            SystemMessage(content="你是一个专业作家，请根据研究资料撰写一篇结构清晰的短文。用中文写作。"),
            HumanMessage(content=f"主题：{state['task']}\n\n研究资料：{state['research_result']}")
        ]
        response = model.invoke(messages)
        
        print(f"  [作家] 完成初稿，共 {len(response.content)} 字")
        
        return {
            "draft": response.content,
            "messages": [AIMessage(content=f"[作家] {response.content}")]
        }

    # 编辑 Agent
    def editor(state: TeamState) -> dict:
        """编辑：审核和优化内容"""
        print("  [编辑] 开始审核编辑...")
        
        # 语法检查
        grammar_check = check_grammar.invoke({"text": state["draft"]})
        
        messages = [
            SystemMessage(content="你是一个资深编辑，请审核并优化以下文章，使其更加专业和易读。用中文回复。"),
            HumanMessage(content=f"初稿：{state['draft']}\n\n语法检查：{grammar_check}")
        ]
        response = model.invoke(messages)
        
        print(f"  [编辑] 编辑完成，最终版本 {len(response.content)} 字")
        
        return {
            "final_content": response.content,
            "messages": [AIMessage(content=f"[编辑] {response.content}")]
        }

    # 路由函数
    def route_to_agent(state: TeamState) -> Literal["researcher", "writer", "editor", "complete"]:
        return state["next_agent"]

    # 构建图
    graph = StateGraph(TeamState)
    
    # 添加节点
    graph.add_node("supervisor", supervisor)
    graph.add_node("researcher", researcher)
    graph.add_node("writer", writer)
    graph.add_node("editor", editor)
    
    # 从 START 到 supervisor
    graph.add_edge(START, "supervisor")
    
    # supervisor 根据条件路由
    graph.add_conditional_edges(
        "supervisor",
        route_to_agent,
        {
            "researcher": "researcher",
            "writer": "writer",
            "editor": "editor",
            "complete": END
        }
    )
    
    # 各 Agent 完成后回到 supervisor
    graph.add_edge("researcher", "supervisor")
    graph.add_edge("writer", "supervisor")
    graph.add_edge("editor", "supervisor")
    
    # 编译并运行
    app = graph.compile()
    
    result = app.invoke({
        "task": "写一篇关于人工智能发展的简短介绍",
        "messages": []
    })
    
    print("\n" + "-" * 40)
    print("📝 最终内容：")
    print("-" * 40)
    print(result["final_content"])
    
    return result

# ============================================================
# 示例 2：协作链模式
# ============================================================

def collaborative_chain():
    """
    协作链模式：Agent 按顺序接力处理
    """
    print("\n" + "=" * 60)
    print("示例 2：协作链模式 - 代码审查流程")
    print("=" * 60)

    class ReviewState(TypedDict):
        code: str
        messages: Annotated[list, add_messages]
        security_review: str
        performance_review: str
        style_review: str
        final_report: str

    
    def security_reviewer(state: ReviewState) -> dict:
        """安全审查员"""
        print("  [安全审查] 检查代码安全性...")
        
        messages = [
            SystemMessage(content="你是一个安全专家，请审查代码的安全性问题。用中文简洁回复。"),
            HumanMessage(content=f"代码：\n{state['code']}")
        ]
        response = model.invoke(messages)
        
        return {
            "security_review": response.content,
            "messages": [AIMessage(content=f"[安全审查] {response.content}")]
        }

    def performance_reviewer(state: ReviewState) -> dict:
        """性能审查员"""
        print("  [性能审查] 分析代码性能...")
        
        messages = [
            SystemMessage(content="你是一个性能优化专家，请分析代码的性能问题和优化建议。用中文简洁回复。"),
            HumanMessage(content=f"代码：\n{state['code']}")
        ]
        response = model.invoke(messages)
        
        return {
            "performance_review": response.content,
            "messages": [AIMessage(content=f"[性能审查] {response.content}")]
        }

    def style_reviewer(state: ReviewState) -> dict:
        """代码风格审查员"""
        print("  [风格审查] 检查代码风格...")
        
        messages = [
            SystemMessage(content="你是一个代码风格专家，请检查代码是否符合最佳实践。用中文简洁回复。"),
            HumanMessage(content=f"代码：\n{state['code']}")
        ]
        response = model.invoke(messages)
        
        return {
            "style_review": response.content,
            "messages": [AIMessage(content=f"[风格审查] {response.content}")]
        }

    def report_generator(state: ReviewState) -> dict:
        """报告生成器"""
        print("  [报告生成] 汇总所有审查结果...")
        
        messages = [
            SystemMessage(content="你是一个技术报告撰写者，请汇总以下审查结果，生成一份简洁的审查报告。用中文回复。"),
            HumanMessage(content=f"""
安全审查结果：
{state['security_review']}

性能审查结果：
{state['performance_review']}

风格审查结果：
{state['style_review']}
""")
        ]
        response = model.invoke(messages)
        
        return {"final_report": response.content}

    # 构建顺序执行的图
    graph = StateGraph(ReviewState)
    
    graph.add_node("security", security_reviewer)
    graph.add_node("performance", performance_reviewer)
    graph.add_node("style", style_reviewer)
    graph.add_node("report", report_generator)
    
    # 顺序执行
    graph.add_edge(START, "security")
    graph.add_edge("security", "performance")
    graph.add_edge("performance", "style")
    graph.add_edge("style", "report")
    graph.add_edge("report", END)
    
    app = graph.compile()
    
    # 测试代码
    test_code = '''
def get_user_data(user_id):
    query = f"SELECT * FROM users WHERE id = {user_id}"
    result = db.execute(query)
    data = []
    for row in result:
        data.append(row)
    return data
'''
    
    result = app.invoke({
        "code": test_code,
        "messages": []
    })
    
    print("\n" + "-" * 40)
    print("📋 代码审查报告：")
    print("-" * 40)
    print(result["final_report"])
    
    return result

# ============================================================
# 示例 3：动态分发模式
# ============================================================

def dynamic_dispatch():
    """
    动态分发模式：根据任务类型动态选择 Agent
    """
    print("\n" + "=" * 60)
    print("示例 3：动态分发模式 - 客服系统")
    print("=" * 60)

    class SupportState(TypedDict):
        query: str
        category: str
        messages: Annotated[list, add_messages]
        response: str

    
    def classifier(state: SupportState) -> dict:
        """分类器：识别问题类型"""
        print("  [分类器] 分析问题类型...")
        
        messages = [
            SystemMessage(content="""分析用户问题，返回分类：
- billing：账单、付款、退款相关
- technical：技术问题、Bug、使用方法
- general：其他一般性问题
只返回分类名称，不要其他内容。"""),
            HumanMessage(content=state["query"])
        ]
        response = model.invoke(messages)
        category = response.content.strip().lower()
        
        # 确保返回有效分类
        if category not in ["billing", "technical", "general"]:
            category = "general"
        
        print(f"  [分类器] 问题分类为：{category}")
        return {"category": category}

    def billing_agent(state: SupportState) -> dict:
        """账单客服"""
        print("  [账单客服] 处理账单问题...")
        
        messages = [
            SystemMessage(content="你是专业的账单客服，擅长处理付款、退款、账单查询等问题。请友好地回复用户。用中文回复。"),
            HumanMessage(content=state["query"])
        ]
        response = model.invoke(messages)
        
        return {"response": f"💰 [账单客服] {response.content}"}

    def technical_agent(state: SupportState) -> dict:
        """技术支持"""
        print("  [技术支持] 处理技术问题...")
        
        messages = [
            SystemMessage(content="你是专业的技术支持工程师，擅长解决技术问题、Bug和使用指导。请专业地回复用户。用中文回复。"),
            HumanMessage(content=state["query"])
        ]
        response = model.invoke(messages)
        
        return {"response": f"🔧 [技术支持] {response.content}"}

    def general_agent(state: SupportState) -> dict:
        """通用客服"""
        print("  [通用客服] 处理一般问题...")
        
        messages = [
            SystemMessage(content="你是友好的客服代表，请热情地回复用户的问题。用中文回复。"),
            HumanMessage(content=state["query"])
        ]
        response = model.invoke(messages)
        
        return {"response": f"😊 [客服] {response.content}"}

    def route_to_specialist(state: SupportState) -> Literal["billing", "technical", "general"]:
        return state["category"]

    # 构建图
    graph = StateGraph(SupportState)
    
    graph.add_node("classifier", classifier)
    graph.add_node("billing", billing_agent)
    graph.add_node("technical", technical_agent)
    graph.add_node("general", general_agent)
    
    graph.add_edge(START, "classifier")
    
    graph.add_conditional_edges(
        "classifier",
        route_to_specialist,
        {
            "billing": "billing",
            "technical": "technical",
            "general": "general"
        }
    )
    
    graph.add_edge("billing", END)
    graph.add_edge("technical", END)
    graph.add_edge("general", END)
    
    app = graph.compile()
    
    # 测试不同类型的问题
    test_queries = [
        "我想申请退款，上个月的订阅费用扣错了",
        "软件打开后一直显示加载中，怎么解决？",
        "你们公司在哪里？营业时间是什么？"
    ]
    
    for query in test_queries:
        print(f"\n用户问题: {query}")
        result = app.invoke({"query": query, "messages": []})
        print(f"回复: {result['response']}")
    
    return result

# ============================================================
# 主程序
# ============================================================

if __name__ == "__main__":
    print("多 Agent 协作教程")
    print("=" * 60)
    
    supervisor_pattern()
    collaborative_chain()
    dynamic_dispatch()
    
    print("\n" + "=" * 60)
    print("✅ 所有示例运行完成！")
    print("=" * 60)
