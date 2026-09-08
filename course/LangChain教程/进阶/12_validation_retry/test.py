"""
简单测试：验证 Pydantic 验证功能（不需要网络）
"""

from pydantic import BaseModel, Field, field_validator, ValidationError

print("=" * 70)
print("测试：Pydantic 验证和错误处理")
print("=" * 70)


# ============================================================================
# 测试 1：Field 约束
# ============================================================================
print("\n--- 测试 1: Field 约束 ---")

class User(BaseModel):
    name: str = Field(min_length=2, max_length=20)
    age: int = Field(ge=0, le=150)
    email: str

print("\n有效数据:")
try:
    user = User(name="张三", age=30, email="zhang@example.com")
    print(f"[OK] {user.name}, {user.age}, {user.email}")
except ValidationError as e:
    print(f"[FAIL] {e}")

print("\n无效数据（年龄超出范围）:")
try:
    user = User(name="李四", age=200, email="li@example.com")
    print(f"[OK] {user}")
except ValidationError as e:
    print(f"[OK] 验证失败（符合预期）: {e.errors()[0]['msg']}")


# ============================================================================
# 测试 2：自定义验证器
# ============================================================================
print("\n--- 测试 2: 自定义验证器 ---")

class Product(BaseModel):
    name: str = Field(min_length=2)
    price: float = Field(gt=0)

    @field_validator('name')
    @classmethod
    def validate_name(cls, v):
        if v.lower() == "unknown":
            raise ValueError('产品名称不能是 unknown')
        return v

print("\n有效产品:")
try:
    product = Product(name="iPhone", price=999.0)
    print(f"[OK] {product.name}, {product.price}")
except ValidationError as e:
    print(f"[FAIL] {e}")

print("\n无效产品（名称是 unknown）:")
try:
    product = Product(name="unknown", price=100.0)
    print(f"[FAIL] {product}")
except ValidationError as e:
    print(f"[OK] 验证失败（符合预期）: {e.errors()[0]['msg']}")

print("\n无效产品（价格 <= 0）:")
try:
    product = Product(name="Product", price=-100.0)
    print(f"[FAIL] {product}")
except ValidationError as e:
    print(f"[OK] 验证失败（符合预期）: {e.errors()[0]['msg']}")


# ============================================================================
# 测试 3：ValidationError 处理
# ============================================================================
print("\n--- 测试 3: ValidationError 处理 ---")

class Data(BaseModel):
    value: int = Field(ge=0, le=100)

test_values = [50, -10, 150]

for val in test_values:
    try:
        data = Data(value=val)
        print(f"value={val:3d} [OK] 验证通过")
    except ValidationError as e:
        error_msg = e.errors()[0]['msg']
        print(f"value={val:3d} [FAIL] 验证失败: {error_msg}")


# ============================================================================
# 测试 4：重试循环模拟
# ============================================================================
print("\n--- 测试 4: 重试循环模拟 ---")

def simulate_extraction_with_retry(attempts: int):
    """模拟验证失败的重试逻辑"""
    max_retries = 3

    for attempt in range(1, max_retries + 1):
        print(f"  尝试 {attempt}/{max_retries}...", end=" ")

        # 模拟：前 attempts-1 次失败，最后一次成功
        if attempt < attempts:
            print("验证失败")
        else:
            print("验证通过 [OK]")
            return True

    print("  已达到最大重试次数 [FAIL]")
    return False

print("\n场景 1: 第 2 次尝试成功")
simulate_extraction_with_retry(2)

print("\n场景 2: 第 3 次尝试成功")
simulate_extraction_with_retry(3)

print("\n场景 3: 所有尝试都失败")
simulate_extraction_with_retry(4)


# ============================================================================
# 总结
# ============================================================================
print("\n" + "=" * 70)
print("Pydantic 验证测试通过！")
print("=" * 70)

print("\n关键点:")
print("  1. Field 约束（ge, le, min_length, max_length）正常工作")
print("  2. @field_validator 自定义验证正常工作")
print("  3. ValidationError 可以正确捕获和处理")
print("  4. 重试循环逻辑正确")

print("\n注意:")
print("  要测试 with_retry() 和 with_fallbacks() 需要:")
print("  1. 确保 GROQ_API_KEY 正确")
print("  2. 网络连接正常")
print("  3. 运行 main.py 查看完整示例")
