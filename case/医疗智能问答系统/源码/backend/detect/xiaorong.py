import numpy as np
import matplotlib.pyplot as plt

# ===== 原始数据 =====
models = ["B3", "B5", "B8"]

QWK = np.array([0.8692, 0.8689, 0.8751])
ACC = np.array([0.8142, 0.7978, 0.8087])
PARAMS = np.array([10.7, 28.4, 84.6])      # 越小越好
TIME = np.array([18.8, 27.5, 42.9])        # 越小越好

# ===== 归一化（0~1）=====
def normalize(x):
    return (x - x.min()) / (x.max() - x.min() + 1e-6)

radar_data = np.vstack([
    normalize(QWK),
    normalize(ACC),
    1 - normalize(PARAMS),   # 取反
    1 - normalize(TIME)      # 取反
])

labels = ["QWK", "Accuracy", "Model Compactness", "Inference Efficiency"]

# ===== Radar 配置 =====
angles = np.linspace(0, 2*np.pi, len(labels), endpoint=False)
angles = np.concatenate([angles, [angles[0]]])

fig = plt.figure(figsize=(7, 7))
ax = fig.add_subplot(111, polar=True)

for i, model in enumerate(models):
    values = radar_data[:, i]
    values = np.concatenate([values, [values[0]]])
    
    ax.plot(angles, values, linewidth=2, label=model)
    ax.fill(angles, values, alpha=0.15)

ax.set_thetagrids(angles[:-1] * 180/np.pi, labels)
ax.set_ylim(0, 1)
ax.set_title("EfficientNet 模型综合性能雷达图", fontsize=14, pad=20)
ax.legend(loc="upper right", bbox_to_anchor=(1.25, 1.1))

plt.tight_layout()
plt.savefig("figures/Radar_EfficientNet_B3_B5_B8.png", dpi=300)
plt.show()
