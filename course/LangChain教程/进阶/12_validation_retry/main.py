"""
LangChain 1.0 - Validation & Retry (验证和重试)
===============================================

本模块重点讲解：
1. with_retry() - 自动重试机制
2. with_fallbacks() - 降级/备用方案
3. Pydantic 验证错误处理
4. 自定义验证逻辑
5. 重试循环实现
"""

import os
from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from pydantic import BaseModel, Field, field_validator, ValidationError
from typing import Optional, List
from enum import Enum
import time

load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not GROQ_API_KEY or GROQ_API_KEY == "your_groq_api_key_here_replace_this":
    raise ValueError("请先设置 GROQ_API_KEY")

model = init_chat_model("groq:llama-3.3-70b-versatile", api_key=GROQ_API_KEY)


# ============================================================================
# 示例 1：with_retry() - 自动重试
# ============================================================================
def example_1_with_retry():
    """
    示例1：使用 with_retry() 处理网络错误

    当遇到临时性错误（网络超时、API限流等）时自动重试
    """
    print("\n" + "="*70)
    print("示例 1：with_retry() - 自动重试机制")
    print("="*70)

    # 创建带重试的 LLM
    llm_with_retry = model.with_retry(
        retry_if_exception_type=(ConnectionError, TimeoutError),  # 重试的异常类型
        wait_exponential_jitter=True,  # 指数退避 + 随机抖动
        stop_after_attempt=3  # 最多重试 3 次
    )

    print("\n配置:")
    print("  - 重试异常: ConnectionError, TimeoutError")
    print("  - 最大重试次数: 3")
    print("  - 退避策略: 指数退避 + 随机抖动")

    try:
        print("\n调用 LLM (如果失败会自动重试)...")
        response = llm_with_retry.invoke("你好")
        print(f"响应: {response.content[:50]}...")
        print("\n✓ 调用成功")
    except Exception as e:
        print(f"\n✗ 重试 3 次后仍然失败: {e}")

    print("\n关键点:")
    print("  - with_retry() 是 Runnable 接口的方法")
    print("  - 适用于临时性错误（网络波动、API限流）")
    print("  - 不适用于逻辑错误（提示词错误、参数错误）")


# ============================================================================
# 示例 2：with_fallbacks() - 降级方案
# ============================================================================
def example_2_with_fallbacks():
    """
    示例2：使用 with_fallbacks() 实现降级

    主模型失败时，自动切换到备用模型
    """
    print("\n" + "="*70)
    print("示例 2：with_fallbacks() - 降级/备用方案")
    print("="*70)

    # 主模型（假设可能失败）
    primary_model = model

    # 备用模型（更可靠或更便宜）
    fallback_model = init_chat_model("groq:llama-3.1-8b-instant", api_key=GROQ_API_KEY)

    # 配置降级
    llm_with_fallbacks = primary_model.with_fallbacks([fallback_model])

    print("\n配置:")
    print("  - 主模型: llama-3.3-70b-versatile")
    print("  - 备用模型: llama-3.1-8b-instant")

    try:
        response = llm_with_fallbacks.invoke("用一句话介绍 Python")
        print(f"\n响应: {response.content}")
        print("\n关键点:")
        print("  - 主模型成功 → 使用主模型响应")
        print("  - 主模型失败 → 自动切换到备用模型")
        print("  - 适用于高可用性场景")
    except Exception as e:
        print(f"\n所有模型都失败: {e}")


# ============================================================================
# 示例 3：Pydantic 字段验证
# ============================================================================
class User(BaseModel):
    """用户信息（带验证）"""
    name: str = Field(description="姓名", min_length=2, max_length=20)
    age: int = Field(description="年龄", ge=0, le=150)  # 0-150 岁
    email: str = Field(description="邮箱")

    @field_validator('email')
    @classmethod
    def validate_email(cls, v):
        """自定义邮箱验证"""
        if '@' not in v:
            raise ValueError('邮箱必须包含 @')
        return v


def example_3_pydantic_validation():
    """
    示例3：Pydantic 内置验证

    使用 Field 约束和自定义验证器
    """
    print("\n" + "="*70)
    print("示例 3：Pydantic 字段验证")
    print("="*70)

    print("\n测试 1: 有效数据")
    try:
        user = User(name="张三", age=30, email="zhang@example.com")
        print(f"✓ 验证通过: {user.name}, {user.age}, {user.email}")
    except ValidationError as e:
        print(f"✗ 验证失败: {e}")

    print("\n测试 2: 年龄超出范围")
    try:
        user = User(name="李四", age=200, email="li@example.com")
        print(f"✓ 验证通过: {user}")
    except ValidationError as e:
        print(f"✗ 验证失败: 年龄必须在 0-150 之间")
        print(f"   错误详情: {e.errors()[0]['msg']}")

    print("\n测试 3: 邮箱格式错误")
    try:
        user = User(name="王五", age=25, email="invalid-email")
        print(f"✓ 验证通过: {user}")
    except ValidationError as e:
        print(f"✗ 验证失败: 邮箱格式错误")
        print(f"   错误详情: {e.errors()[0]['msg']}")

    print("\n关键点:")
    print("  - Field(ge=, le=) - 数值范围约束")
    print("  - Field(min_length=, max_length=) - 字符串长度约束")
    print("  - @field_validator - 自定义验证逻辑")
    print("  - ValidationError - 验证失败时抛出")


# ============================================================================
# 示例 4：LLM 输出验证 + 重试
# ============================================================================
class Product(BaseModel):
    """产品信息（严格验证）"""
    name: str = Field(description="产品名称（字符串类型）", min_length=2)
    price: float = Field(description="价格，数字类型（必须 > 0）", gt=0)
    stock: int = Field(description="库存，整数类型（必须 >= 0）", ge=0)

    @field_validator('name')
    @classmethod
    def validate_name(cls, v):
        if v.lower() == "unknown":
            raise ValueError('产品名称不能是 unknown')
        return v


def example_4_llm_validation_retry():
    """
    示例4：LLM 输出验证 + 重试循环

    如果 LLM 输出不符合验证规则，重新提示并重试
    """
    print("\n" + "="*70)
    print("示例 4：LLM 输出验证 + 重试循环")
    print("="*70)

    structured_llm = model.with_structured_output(Product)

    max_retries = 3

    # 使用一个简单的测试案例（改为正常价格，避免触发验证错误）
    text = "iPhone 15 售价 5999 元，库存 50 件"

    print(f"\n提取文本: {text}")
    print(f"验证规则: price > 0, stock >= 0, name 不能是 'unknown'\n")

    for attempt in range(1, max_retries + 1):
        print(f"尝试 {attempt}/{max_retries}...")

        try:
            # 调用 LLM
            prompt = f"""从以下文本提取产品信息。
重要：price 必须是数字类型（不是字符串），stock 必须是整数类型。

文本: {text}"""
            result = structured_llm.invoke(prompt)

            # 如果到这里，说明验证通过
            print(f"✓ 提取成功!")
            print(f"  产品: {result.name}")
            print(f"  价格: {result.price} 元")
            print(f"  库存: {result.stock} 件")
            break

        except ValidationError as e:
            print(f"✗ Pydantic 验证失败: {e.errors()[0]['msg']}")

            if attempt < max_retries:
                error_msg = e.errors()[0]['msg']
                text = f"{text}\n注意: {error_msg}"
                print(f"  → 修正提示后重试...\n")
            else:
                print(f"  → 已达到最大重试次数")

        except Exception as e:
            # 捕获其他错误（如 BadRequestError）
            error_str = str(e)
            if "expected number, but got string" in error_str:
                print(f"✗ API 验证失败: LLM 返回了字符串而不是数字")
            elif "expected integer, but got string" in error_str:
                print(f"✗ API 验证失败: LLM 返回了字符串而不是整数")
            else:
                print(f"✗ 其他错误: {e}")

            if attempt < max_retries:
                print(f"  → 重试...\n")
                # 强化提示
                text = f"{text}\n重要: price 和 stock 必须是数字类型，不能是字符串"
            else:
                print(f"  → 已达到最大重试次数")
                print(f"\n说明: 某些模型可能会返回字符串类型的数字，")
                print(f"      这会导致 API 端验证失败。")

    print("\n关键点:")
    print("  - ValidationError 捕获 Pydantic 验证失败")
    print("  - Exception 捕获 API 端验证失败")
    print("  - 在提示中强调类型要求")
    print("  - 限制最大重试次数防止无限循环")


# ============================================================================
# 示例 5：自定义验证函数
# ============================================================================
class Article(BaseModel):
    """文章信息"""
    title: str = Field(description="标题")
    content: str = Field(description="内容")
    word_count: int = Field(description="字数")


def validate_article(article: Article) -> bool:
    """
    自定义验证逻辑

    检查 word_count 是否与 content 实际字数接近
    """
    actual_count = len(article.content)
    claimed_count = article.word_count

    # 允许 10% 误差
    tolerance = 0.1
    lower_bound = actual_count * (1 - tolerance)
    upper_bound = actual_count * (1 + tolerance)

    if not (lower_bound <= claimed_count <= upper_bound):
        return False

    return True


def example_5_custom_validation():
    """
    示例5：自定义验证函数

    Pydantic 验证之外的业务逻辑验证
    """
    print("\n" + "="*70)
    print("示例 5：自定义验证函数")
    print("="*70)

    print("\n测试 1: 字数匹配")
    article1 = Article(
        title="测试文章",
        content="这是一篇测试文章的内容",
        word_count=12
    )

    if validate_article(article1):
        print(f"✓ 验证通过: 声称字数 {article1.word_count}，实际 {len(article1.content)}")
    else:
        print(f"✗ 验证失败: 字数不匹配")

    print("\n测试 2: 字数不匹配（相差太大）")
    article2 = Article(
        title="测试文章",
        content="短内容",
        word_count=1000  # 明显错误
    )

    if validate_article(article2):
        print(f"✓ 验证通过")
    else:
        print(f"✗ 验证失败: 声称 {article2.word_count} 字，实际只有 {len(article2.content)} 字")

    print("\n关键点:")
    print("  - Pydantic 验证类型和格式")
    print("  - 自定义函数验证业务逻辑")
    print("  - 可以结合使用实现完整验证")


# ============================================================================
# 示例 6：完整的验证 + 重试工作流
# ============================================================================
class ExtractedData(BaseModel):
    """提取的数据（完整验证）"""
    name: str = Field(description="名称（字符串类型）", min_length=1)
    value: float = Field(description="数值（数字类型，必须 > 0）", gt=0)

    @field_validator('name')
    @classmethod
    def validate_name(cls, v):
        if v.strip() == "":
            raise ValueError('名称不能为空')
        return v.strip()


def extract_with_validation(text: str, max_retries: int = 3) -> Optional[ExtractedData]:
    """
    带验证的提取函数

    Args:
        text: 待提取的文本
        max_retries: 最大重试次数

    Returns:
        提取的数据（验证通过）或 None（失败）
    """
    structured_llm = model.with_structured_output(ExtractedData)

    current_text = text

    for attempt in range(1, max_retries + 1):
        try:
            # 调用 LLM（强调类型）
            prompt = f"""提取以下文本中的信息。
重要：value 必须是数字类型（float），不能是字符串。

{current_text}"""
            result = structured_llm.invoke(prompt)

            # 额外的业务验证（Pydantic 已经检查了 gt=0）
            # 所有验证通过
            return result

        except ValidationError as e:
            error_msg = e.errors()[0]['msg']
            if attempt < max_retries:
                current_text = f"{text}\n\n注意：{error_msg}。请重新提取。"
            else:
                return None

        except Exception as e:
            # 捕获 API 错误
            if attempt < max_retries:
                current_text = f"{text}\n\n重要：value 必须是数字类型，不能是字符串。"
            else:
                return None

    return None


def example_6_complete_workflow():
    """
    示例6：完整的验证 + 重试工作流

    展示生产环境中的最佳实践
    """
    print("\n" + "="*70)
    print("示例 6：完整的验证 + 重试工作流")
    print("="*70)

    test_cases = [
        "产品 A 的价值是 999.99 元",
        "产品 B 的价值是 1299 元",
    ]

    for i, text in enumerate(test_cases, 1):
        print(f"\n--- 测试用例 {i} ---")
        print(f"文本: {text}")

        result = extract_with_validation(text, max_retries=2)

        if result:
            print(f"✓ 提取成功:")
            print(f"  名称: {result.name}")
            print(f"  数值: {result.value}")
        else:
            print(f"✗ 提取失败（重试 2 次后仍无法通过验证）")

    print("\n关键点:")
    print("  - 封装验证逻辑到函数中")
    print("  - 清晰的错误处理")
    print("  - 返回 Optional 表示可能失败")
    print("  - 适合集成到生产系统")


# ============================================================================
# 示例 7：组合使用 retry + fallbacks + validation
# ============================================================================
def example_7_combined():
    """
    示例7：组合使用多种策略

    网络重试 + 模型降级 + 输出验证

    重要：调用顺序必须是：
    1. 先 with_structured_output()
    2. 再 with_retry()
    3. 最后 with_fallbacks()
    """
    print("\n" + "="*70)
    print("示例 7：组合策略 - retry + fallbacks + validation")
    print("="*70)

    # 1. 先创建结构化输出（必须先调用！）
    structured_primary = model.with_structured_output(ExtractedData)

    # 2. 配置备用模型（也要先创建结构化输出）
    fallback_model = init_chat_model("groq:llama-3.1-8b-instant", api_key=GROQ_API_KEY)
    structured_fallback = fallback_model.with_structured_output(ExtractedData)

    # 3. 添加重试（在结构化输出之后）
    primary_with_retry = structured_primary.with_retry(
        retry_if_exception_type=(ConnectionError, TimeoutError),
        stop_after_attempt=2
    )

    # 4. 添加降级（最后一步）
    robust_llm = primary_with_retry.with_fallbacks([structured_fallback])

    print("\n配置（正确的调用顺序）:")
    print("  1. 先创建结构化输出 (with_structured_output)")
    print("  2. 再添加重试机制 (with_retry)")
    print("  3. 最后添加降级方案 (with_fallbacks)")

    try:
        prompt = """提取以下文本中的信息。
重要：value 必须是数字类型（float）。

产品 C 的价值是 1299 元"""
        result = robust_llm.invoke(prompt)
        print(f"\n✓ 成功提取:")
        print(f"  名称: {result.name}")
        print(f"  数值: {result.value}")
    except Exception as e:
        print(f"\n✗ 所有策略都失败: {e}")

    print("\n关键点:")
    print("  - 调用顺序很重要！")
    print("  - with_structured_output() 必须在最前面")
    print("  - 然后是 retry、fallbacks")
    print("  - 多层防护: 验证 → 重试 → 降级")
    print("  - 生产环境推荐配置")


# ============================================================================
# 主程序
# ============================================================================
def main():
    print("\n" + "="*70)
    print(" LangChain 1.0 - Validation & Retry (验证和重试)")
    print("="*70)

    try:
        # example_1_with_retry()
        # input("\n按 Enter 继续...")

        # example_2_with_fallbacks()
        # input("\n按 Enter 继续...")

        # example_3_pydantic_validation()
        # input("\n按 Enter 继续...")

        # example_4_llm_validation_retry()
        # input("\n按 Enter 继续...")

        # example_5_custom_validation()
        # input("\n按 Enter 继续...")

        example_6_complete_workflow()
        input("\n按 Enter 继续...")

        example_7_combined()

        print("\n" + "="*70)
        print(" 完成！")
        print("="*70)
        print("\n核心要点：")
        print("  1. with_retry() - 网络错误自动重试")
        print("  2. with_fallbacks() - 模型降级/备用方案")
        print("  3. Pydantic Field 约束 - 类型和格式验证")
        print("  4. @field_validator - 自定义字段验证")
        print("  5. ValidationError - 捕获验证失败")
        print("  6. 重试循环 - LLM 输出验证失败时重试")
        print("  7. 组合策略 - retry + fallbacks + validation")
        print("\n生产环境建议：")
        print("  - 网络调用 → with_retry()")
        print("  - 高可用性 → with_fallbacks()")
        print("  - 数据质量 → Pydantic 验证 + 重试循环")
        print("\n下一步：")
        print("  13_rag_basics - RAG 基础（文档加载、向量存储、检索）")

    except KeyboardInterrupt:
        print("\n\n程序中断")
    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
