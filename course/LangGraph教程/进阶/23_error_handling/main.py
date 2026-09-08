"""
模块 23：错误处理
学习如何实现健壮的错误处理和恢复机制
"""

import os
import time
import random
from typing import Optional, Any
from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableLambda, RunnableConfig

# ==================== JSON 解析辅助函数 ====================

def safe_parse_json(text: str, default: dict = None) -> dict:
    """
    安全地解析JSON文本
    
    处理：
    - Markdown 代码块 (```json ... ```)
    - 前后的空白字符
    - 解析失败时返回默认值
    """
    if default is None:
        default = {}
    
    content = text.strip()
    
    # 移除 Markdown 代码块
    if "```json" in content:
        try:
            content = content.split("```json")[1].split("```")[0]
        except IndexError:
            pass
    elif "```" in content:
        try:
            parts = content.split("```")
            if len(parts) >= 2:
                content = parts[1]
        except IndexError:
            pass
    
    content = content.strip()
    
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        print(f"   ⚠️ JSON 解析失败: {e}")
        return default



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

    # 初始化模型

# ============================================================
# 示例 1：基本重试机制
# ============================================================

def basic_retry():
    """
    实现基本的重试机制
    """
    print("\n" + "=" * 60)
    print("示例 1：基本重试机制")
    print("=" * 60)

    def retry_with_backoff(
        func,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0
    ):
        """
        带指数退避的重试装饰器
        """
        def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    
                    if attempt < max_retries - 1:
                        # 计算等待时间（指数退避 + 随机抖动）
                        delay = min(base_delay * (2 ** attempt), max_delay)
                        jitter = random.uniform(0, delay * 0.1)
                        wait_time = delay + jitter
                        
                        print(f"  ⚠️ 尝试 {attempt + 1} 失败: {e}")
                        print(f"     等待 {wait_time:.1f} 秒后重试...")
                        time.sleep(wait_time)
                    else:
                        print(f"  ❌ 所有 {max_retries} 次尝试均失败")
            
            raise last_exception
        
        return wrapper

    # 模拟不稳定的函数
    call_count = [0]
    
    def unstable_function(query: str):
        """模拟一个可能失败的函数"""
        call_count[0] += 1
        
        # 前两次调用失败
        if call_count[0] <= 2:
            raise ConnectionError(f"模拟网络错误 (尝试 {call_count[0]})")
        
        return model.invoke(query)

    # 应用重试
    stable_function = retry_with_backoff(unstable_function, max_retries=3, base_delay=0.5)

    print("调用不稳定函数（前2次会失败）...")
    try:
        result = stable_function("简单回答：1+1等于几？")
        print(f"  ✅ 最终成功: {result.content}")
    except Exception as e:
        print(f"  ❌ 最终失败: {e}")

# ============================================================
# 示例 2：模型回退机制
# ============================================================

def model_fallback():
    """
    实现模型回退：主模型失败时使用备用模型
    """
    print("\n" + "=" * 60)
    print("示例 2：模型回退机制")
    print("=" * 60)

    class FallbackChain:
        """带回退的模型链"""
        
        def __init__(self, models: list):
            self.models = models
        
        def invoke(self, query: str) -> Any:
            last_error = None
            
            for i, model in enumerate(self.models):
                model_name = f"模型 {i + 1}"
                try:
                    print(f"  尝试 {model_name}...")
                    result = model.invoke(query)
                    print(f"  ✅ {model_name} 成功")
                    return result
                except Exception as e:
                    last_error = e
                    print(f"  ⚠️ {model_name} 失败: {e}")
            
            raise Exception(f"所有模型都失败: {last_error}")

    # 创建模型列表（实际使用时可以用不同的模型）
    models = [
        model,  # 主模型
        model,  # 备用模型 1
        model,  # 备用模型 2
    ]

    fallback_chain = FallbackChain(models)
    
    print("使用回退链调用...")
    result = fallback_chain.invoke("什么是 Python？用一句话回答。")
    print(f"  结果: {result.content}")

# ============================================================
# 示例 3：输出验证和修复
# ============================================================

def output_validation():
    """
    验证 LLM 输出并在需要时重试或修复
    """
    print("\n" + "=" * 60)
    print("示例 3：输出验证和修复")
    print("=" * 60)

    class ProductInfo(BaseModel):
        """产品信息结构"""
        name: str = Field(description="产品名称")
        price: float = Field(gt=0, description="价格（必须大于0）")
        category: str = Field(description="类别")

    def extract_product_info(description: str, max_retries: int = 3) -> ProductInfo:
        """
        从描述中提取产品信息，带验证和重试
        """
        prompt = f"""从以下描述中提取产品信息，返回 JSON 格式：
{{"name": "产品名称", "price": 数字价格, "category": "类别"}}

描述: {description}

只返回 JSON，不要其他内容。"""

        for attempt in range(max_retries):
            try:
                response = model.invoke(prompt)
                content = response.content.strip()
                
                # 使用安全的 JSON 解析
                data = safe_parse_json(content, None)
                
                if data is None:
                    raise json.JSONDecodeError("解析失败", content, 0)
                
                # 验证数据
                product = ProductInfo(**data)
                print(f"  ✅ 验证通过 (尝试 {attempt + 1})")
                return product
                
            except json.JSONDecodeError as e:
                print(f"  ⚠️ JSON 解析失败 (尝试 {attempt + 1}): {e}")
            except ValidationError as e:
                print(f"  ⚠️ 数据验证失败 (尝试 {attempt + 1}): {e}")
            except Exception as e:
                print(f"  ⚠️ 其他错误 (尝试 {attempt + 1}): {e}")
        
        # 返回默认值
        print("  ℹ️ 使用默认值")
        return ProductInfo(name="未知产品", price=0.01, category="未分类")

    # 测试
    descriptions = [
        "我们的新款蓝牙耳机售价299元，属于电子产品类别",
        "这是一个测试"  # 可能导致解析问题
    ]

    for desc in descriptions:
        print(f"\n描述: {desc}")
        product = extract_product_info(desc)
        print(f"  结果: {product}")

# ============================================================
# 示例 4：优雅降级
# ============================================================

def graceful_degradation():
    """
    实现优雅降级：部分功能失败时继续运行
    """
    print("\n" + "=" * 60)
    print("示例 4：优雅降级")
    print("=" * 60)

    class RobustAssistant:
        """具有优雅降级能力的助手"""
        
        def __init__(self, model):
            self.model = model
            self.features = {
                "summarization": True,
                "translation": True,
                "sentiment": True
            }
        
        def _safe_call(self, feature: str, prompt: str, default: str = "功能暂时不可用") -> str:
            """安全调用，失败时返回默认值"""
            if not self.features.get(feature, False):
                return f"[{feature}] {default}"
            
            try:
                response = self.model.invoke(prompt)
                return response.content
            except Exception as e:
                print(f"  ⚠️ {feature} 功能出错: {e}")
                self.features[feature] = False  # 标记为不可用
                return f"[{feature}] {default}"
        
        def process(self, text: str) -> dict:
            """处理文本，各功能独立执行"""
            results = {}
            
            print("  执行摘要...")
            results["summary"] = self._safe_call(
                "summarization",
                f"用一句话总结：{text}"
            )
            
            print("  执行翻译...")
            results["translation"] = self._safe_call(
                "translation",
                f"翻译成英文：{text}"
            )
            
            print("  执行情感分析...")
            results["sentiment"] = self._safe_call(
                "sentiment",
                f"分析情感（正面/负面/中性）：{text}"
            )
            
            return results

    assistant = RobustAssistant(model)
    
    # 模拟某个功能失败
    print("模拟 translation 功能不可用...")
    assistant.features["translation"] = False
    
    text = "今天天气真好，适合出去散步。"
    print(f"\n处理文本: {text}")
    
    results = assistant.process(text)
    
    print("\n结果:")
    for key, value in results.items():
        print(f"  {key}: {value}")

# ============================================================
# 示例 5：全局错误处理框架
# ============================================================

def global_error_handling():
    """
    实现统一的全局错误处理框架
    """
    print("\n" + "=" * 60)
    print("示例 5：全局错误处理框架")
    print("=" * 60)

    class ErrorHandler:
        """全局错误处理器"""
        
        def __init__(self):
            self.error_log = []
        
        def handle(self, error: Exception, context: dict = None) -> dict:
            """
            统一处理错误
            返回包含用户友好消息和内部详情的字典
            """
            error_type = type(error).__name__
            error_message = str(error)
            
            # 记录错误
            log_entry = {
                "type": error_type,
                "message": error_message,
                "context": context,
                "timestamp": time.time()
            }
            self.error_log.append(log_entry)
            
            # 根据错误类型返回适当的用户消息
            user_messages = {
                "ConnectionError": "网络连接失败，请检查网络后重试",
                "TimeoutError": "请求超时，请稍后重试",
                "ValueError": "输入数据无效，请检查输入",
                "AuthenticationError": "认证失败，请检查 API 密钥",
                "RateLimitError": "请求过于频繁，请稍后重试"
            }
            
            user_message = user_messages.get(
                error_type, 
                "处理请求时出现问题，请稍后重试"
            )
            
            return {
                "success": False,
                "user_message": user_message,
                "error_type": error_type,
                "can_retry": error_type in ["ConnectionError", "TimeoutError", "RateLimitError"]
            }
        
        def get_error_stats(self) -> dict:
            """获取错误统计"""
            if not self.error_log:
                return {"total": 0, "by_type": {}}
            
            by_type = {}
            for entry in self.error_log:
                error_type = entry["type"]
                by_type[error_type] = by_type.get(error_type, 0) + 1
            
            return {
                "total": len(self.error_log),
                "by_type": by_type
            }

    # 创建全局错误处理器
    error_handler = ErrorHandler()

    def safe_invoke(query: str) -> dict:
        """使用全局错误处理的安全调用"""
        try:
            response = model.invoke(query)
            return {
                "success": True,
                "content": response.content
            }
        except Exception as e:
            return error_handler.handle(e, context={"query": query})

    # 测试
    print("测试正常调用...")
    result = safe_invoke("你好！")
    print(f"  结果: {result}")

    # 模拟错误
    print("\n模拟错误情况...")
    error_result = error_handler.handle(
        ConnectionError("Connection refused"),
        context={"action": "test"}
    )
    print(f"  错误处理结果: {error_result}")

    # 查看统计
    print(f"\n错误统计: {error_handler.get_error_stats()}")

# ============================================================
# 示例 6：超时处理
# ============================================================

def timeout_handling():
    """
    实现请求超时处理
    """
    print("\n" + "=" * 60)
    print("示例 6：超时处理")
    print("=" * 60)

    import concurrent.futures

    def invoke_with_timeout(model, query: str, timeout: float = 30.0):
        """
        带超时的模型调用
        """
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(model.invoke, query)
            try:
                result = future.result(timeout=timeout)
                return {"success": True, "content": result.content}
            except concurrent.futures.TimeoutError:
                return {
                    "success": False,
                    "error": "请求超时",
                    "timeout": timeout
                }

    # 测试
    print("测试带超时的调用（超时设置：30秒）...")
    result = invoke_with_timeout(model, "你好！", timeout=30.0)
    print(f"  结果: {result}")

# ============================================================
# 主程序
# ============================================================

if __name__ == "__main__":
    print("错误处理教程")
    print("=" * 60)
    
    basic_retry()
    model_fallback()
    output_validation()
    graceful_degradation()
    global_error_handling()
    timeout_handling()
    
    print("\n" + "=" * 60)
    print("✅ 所有示例运行完成！")
    print("=" * 60)
