# test_gradcam_densenet121.py
# 论文级 Grad-CAM 可视化（DenseNet121 · 糖网）

import torch
import cv2
import numpy as np
import timm
import albumentations as A
from albumentations.pytorch import ToTensorV2
import matplotlib.pyplot as plt
import os

# ================== 中文字体支持 ==================
plt.rcParams['font.sans-serif'] = [
    'WenQuanYi Micro Hei', 'SimHei', 'Arial Unicode MS'
]
plt.rcParams['axes.unicode_minus'] = False

# ================== 路径配置 ==================
img_path = "data/test_images/0a2b5e1a0be8.png"
model_path = "/njzk/blindness/models/best_densenet121.pth"
save_dir = "figures"
os.makedirs(save_dir, exist_ok=True)

# ================== 类别标签 ==================
labels = [
    '无糖尿病视网膜病变',
    '轻度非增殖性DR',
    '中度非增殖性DR',
    '重度非增殖性DR',
    '增殖性DR（极重）'
]

# ================== 加载模型 ==================
device = 'cuda' if torch.cuda.is_available() else 'cpu'

model = timm.create_model(
    'densenet121',
    pretrained=False,
    num_classes=5
)
model.load_state_dict(torch.load(model_path, map_location=device))
model.eval().to(device)

# ================== 预处理 ==================
transform = A.Compose([
    A.CLAHE(clip_limit=2.0),
    A.Resize(256, 256),
    A.CenterCrop(224, 224),
    A.Normalize(
        mean=[0.485, 0.456, 0.406],
        std=[0.229, 0.224, 0.225]
    ),
    ToTensorV2(),
])

img_bgr = cv2.imread(img_path)
img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
input_tensor = transform(image=img_rgb)['image'].unsqueeze(0).to(device)

# ================== 推理（可 no_grad）==================
with torch.no_grad():
    output = model(input_tensor)
    prob = torch.softmax(output, dim=1)[0].cpu().numpy()
    pred = output.argmax(1).item()

print("\n【模型诊断结果】")
print(f"预测等级：{pred} → {labels[pred]}")
print(f"置信度：{prob[pred]*100:.2f}%")
for i, p in enumerate(prob):
    print(f"  {i}级: {p*100:6.2f}%")

# ================== Grad-CAM（关键部分）==================
from pytorch_grad_cam import GradCAM
from pytorch_grad_cam.utils.model_targets import ClassifierOutputTarget

# ⭐ DenseNet 正确 CAM 层
target_layers = [model.features[-1]]

cam = GradCAM(
    model=model,
    target_layers=target_layers,
    # use_cuda=(device == 'cuda')
)

targets = [ClassifierOutputTarget(pred)]
grayscale_cam = cam(
    input_tensor=input_tensor,
    targets=targets
)[0]  # (224,224)

# ================== 热力图后处理（论文级）==================
# Resize 到原图
cam_resized = cv2.resize(
    grayscale_cam,
    (img_rgb.shape[1], img_rgb.shape[0])
)

# 归一化 + 背景抑制（核心）
cam_resized = np.maximum(cam_resized, 0)
cam_resized = cam_resized / cam_resized.max()
cam_resized[cam_resized < 0.4] = 0  # ⭐ 抑制低响应

# 伪彩色
heatmap = cv2.applyColorMap(
    np.uint8(255 * cam_resized),
    cv2.COLORMAP_JET
)
heatmap = cv2.cvtColor(heatmap, cv2.COLOR_BGR2RGB)

# 只在高响应区域叠加
overlay = img_rgb.copy()
mask = cam_resized > 0
overlay[mask] = (
    0.4 * img_rgb[mask] +
    0.6 * heatmap[mask]
).astype(np.uint8)

# ================== 可视化（三联图）==================
plt.figure(figsize=(18, 8), facecolor='white')

plt.subplot(1, 3, 1)
plt.imshow(img_rgb)
plt.title("原始眼底图像", fontsize=18, fontweight='bold')
plt.axis('off')

plt.subplot(1, 3, 2)
plt.imshow(cam_resized, cmap='jet')
plt.title("模型关注区域（Grad-CAM）", fontsize=18, fontweight='bold')
plt.axis('off')

plt.subplot(1, 3, 3)
plt.imshow(overlay)
plt.title(
    f"诊断结果：{pred}级 - {labels[pred]}\n"
    f"置信度：{prob[pred]*100:.1f}%",
    fontsize=18,
    fontweight='bold',
    color='red'
)
plt.axis('off')

plt.suptitle(
    "糖尿病视网膜病变智能辅助诊断系统",
    fontsize=24,
    fontweight='bold'
)

plt.tight_layout()

# ================== 高清保存 ==================
save_path = os.path.join(
    save_dir,
    f"GradCAM_{labels[pred]}_{pred}级.jpg"
)
plt.savefig(save_path, dpi=300, bbox_inches='tight', facecolor='white')
plt.show()

print(f"\n✅ 诊断报告已保存：{save_path}")
