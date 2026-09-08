import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

plt.rcParams['font.sans-serif'] = ['SimHei', 'Arial Unicode MS']
plt.rcParams['axes.unicode_minus'] = False

df = pd.read_excel("figures/六模型性能对比表.xlsx")

# 按 QWK 排序（论文更合理）
df = df.sort_values("QWK", ascending=False)
models = df["Model"].tolist()
fig, ax1 = plt.subplots(figsize=(10, 6))

x = np.arange(len(models))
width = 0.35

# Accuracy 柱状图
bars = ax1.bar(
    x,
    df["Accuracy"],
    width,
    label="Accuracy",
    alpha=0.85
)

ax1.set_ylabel("Accuracy")
ax1.set_ylim(0.7, 0.85)
ax1.set_xticks(x)
ax1.set_xticklabels(models, rotation=30, ha="right")

# 数值标注
for bar in bars:
    height = bar.get_height()
    ax1.text(bar.get_x() + bar.get_width()/2., height + 0.002,
             f"{height:.3f}", ha="center", fontsize=9)

ax1.legend(loc="upper left")

plt.title("不同骨干网络的分类性能对比")
plt.tight_layout()
plt.savefig("figures/Fig1_Accuracy_QWK_Comparison.png", dpi=300)
plt.show()
plt.figure(figsize=(8, 6))

plt.scatter(
    df["Infer Time(ms)"],
    df["Accuracy"],
    s=df["Params(M)"] * 3,  # 参数量映射为气泡大小
    alpha=0.75
)

for i, model in enumerate(models):
    plt.text(
        df["Infer Time(ms)"][i] + 0.5,
        df["Accuracy"][i],
        model,
        fontsize=9
    )

plt.xlabel("Inference Time (ms)")
plt.ylabel("Accuracy")
plt.title("模型性能与推理效率权衡分析")

plt.grid(alpha=0.3)
plt.tight_layout()
plt.savefig("figures/Fig2_Accuracy_vs_InferenceTime.png", dpi=300)
plt.show()
plt.figure(figsize=(10, 5))

plt.bar(
    models,
    df["Params(M)"],
    alpha=0.85
)

plt.ylabel("Parameters (Million)")
plt.title("不同模型参数规模对比")
plt.xticks(rotation=30, ha="right")

for i, v in enumerate(df["Params(M)"]):
    plt.text(i, v + 1, f"{v:.1f}M", ha="center", fontsize=9)

plt.tight_layout()
plt.savefig("figures/Fig3_Model_Params.png", dpi=300)
plt.show()
