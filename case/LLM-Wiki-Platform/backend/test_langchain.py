"""
LangChain 测试脚本
用于验证 LangChain 1.0+ 安装和配置
"""
import os
import sys
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

def test_imports():
    """测试导入"""
    print("1. 测试 LangChain 导入...")
    try:
        import langchain
        print(f"   ✓ langchain 版本: {langchain.__version__}")
    except ImportError as e:
        print(f"   ✗ langchain 导入失败: {e}")
        return False
    
    try:
        from langchain_openai import ChatOpenAI, OpenAIEmbeddings
        print("   ✓ langchain_openai 导入成功")
    except ImportError as e:
        print(f"   ✗ langchain_openai 导入失败: {e}")
        return False
    
    try:
        from langchain_community.vectorstores import Milvus
        print("   ✓ langchain_community 导入成功")
    except ImportError as e:
        print(f"   ✗ langchain_community 导入失败: {e}")
        return False
    
    try:
        import langgraph
        print(f"   ✓ langgraph 导入成功")
    except ImportError as e:
        print(f"   ✗ langgraph 导入失败: {e}")
        return False
    
    return True

def test_openai_connection():
    """测试 OpenAI 连接"""
    print("\n2. 测试 OpenAI 连接...")
    
    api_key = os.getenv('OPENAI_API_KEY')
    base_url = os.getenv('OPENAI_BASE_URL')
    
    if not api_key:
        print("   ✗ OPENAI_API_KEY 未设置")
        return False
    
    print(f"   ✓ API Key: {api_key[:10]}...")
    print(f"   ✓ Base URL: {base_url}")
    
    try:
        from langchain_openai import ChatOpenAI
        
        llm = ChatOpenAI(
            model=os.getenv('OPENAI_MODEL', 'gpt-5-mini'),
            api_key=api_key,
            base_url=base_url
        )
        
        # 简单测试调用
        response = llm.invoke("Say 'Hello' in one word")
        print(f"   ✓ LLM 调用成功: {response.content}")
        return True
    except Exception as e:
        print(f"   ✗ LLM 调用失败: {e}")
        return False

def test_embeddings():
    """测试 Embeddings"""
    print("\n3. 测试 Embeddings...")
    
    api_key = os.getenv('OPENAI_API_KEY')
    base_url = os.getenv('OPENAI_BASE_URL')
    
    try:
        from langchain_openai import OpenAIEmbeddings
        
        embeddings = OpenAIEmbeddings(
            model=os.getenv('EMBEDDING_MODEL', 'text-embedding-3-small'),
            api_key=api_key,
            base_url=base_url
        )
        
        # 测试嵌入生成
        result = embeddings.embed_query("Test embedding")
        print(f"   ✓ Embedding 生成成功，维度: {len(result)}")
        return True
    except Exception as e:
        print(f"   ✗ Embedding 生成失败: {e}")
        return False

def test_langraph():
    """测试 LangGraph"""
    print("\n4. 测试 LangGraph...")
    
    try:
        from langgraph.graph import StateGraph, END
        from typing import TypedDict, Annotated
        
        # 定义状态
        class TestState(TypedDict):
            input: str
            output: str
        
        # 创建简单的图
        workflow = StateGraph(TestState)
        workflow.add_node("test", lambda state: {"output": f"Processed: {state['input']}"})
        workflow.set_entry_point("test")
        workflow.add_edge("test", END)
        
        app = workflow.compile()
        
        # 运行测试
        result = app.invoke({"input": "Hello"})
        print(f"   ✓ LangGraph 执行成功: {result['output']}")
        return True
    except Exception as e:
        print(f"   ✗ LangGraph 测试失败: {e}")
        return False

def main():
    """主测试函数"""
    print("=" * 50)
    print("LangChain 1.0+ 测试脚本")
    print("=" * 50)
    
    results = []
    
    # 运行测试
    results.append(("导入测试", test_imports()))
    results.append(("OpenAI 连接", test_openai_connection()))
    results.append(("Embeddings", test_embeddings()))
    results.append(("LangGraph", test_langraph()))
    
    # 输出结果
    print("\n" + "=" * 50)
    print("测试结果汇总")
    print("=" * 50)
    
    all_passed = True
    for name, passed in results:
        status = "✓ 通过" if passed else "✗ 失败"
        print(f"{name}: {status}")
        if not passed:
            all_passed = False
    
    print("=" * 50)
    
    if all_passed:
        print("所有测试通过！")
        return 0
    else:
        print("部分测试失败，请检查配置")
        return 1

if __name__ == "__main__":
    sys.exit(main())