import matplotlib.pyplot as plt
import numpy as np

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'Arial Unicode MS']
plt.rcParams['axes.unicode_minus'] = False

# 数据
models = ['EfficientNet-B3', 'EfficientNet-B5', 'EfficientNet-B8']
qwk_values = [0.869, 0.869, 0.875]

x = np.arange(len(models))
width = 0.35

# 创建图形
fig, ax1 = plt.subplots(figsize=(10, 6))

# 绘制柱状图（QWK）- 居中对齐
bars = ax1.bar(x, qwk_values, width, label='QWK', color='#3b82f6', alpha=0.8)

# 在柱状图上添加数值标签（放在柱子内部上方）
for bar, val in zip(bars, qwk_values):
    height = bar.get_height()
    ax1.text(bar.get_x() + bar.get_width()/2., height - 0.008,
             f'{val:.3f}', ha='center', va='top', fontsize=11, fontweight='bold', color='white')

# 设置左侧Y轴
ax1.set_ylabel('QWK', fontsize=12, color='#3b82f6')
ax1.set_ylim(0.82, 0.90)
ax1.tick_params(axis='y', labelcolor='#3b82f6')

# 设置X轴
ax1.set_xticks(x)
ax1.set_xticklabels(models, fontsize=11)
ax1.set_xlabel('模型', fontsize=12)

# 添加标题
plt.title('EfficientNet模型规模消融实验结果', fontsize=14, fontweight='bold', pad=15)

# 添加图例
ax1.legend(loc='upper left', fontsize=10)

# 添加网格线
ax1.grid(axis='y', alpha=0.3, linestyle='--')

# 调整布局
plt.tight_layout()

# 保存图片
output_path = 'Ablation_EfficientNet_B3_B5_B8.png'
plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
print(f"Saved: {output_path}")

plt.show()
