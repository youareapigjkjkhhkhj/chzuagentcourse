import torch
import cv2
import numpy as np
import timm
import albumentations as A
from albumentations.pytorch import ToTensorV2
import matplotlib.pyplot as plt
import os

# ================== 中文字体 ==================
plt.rcParams['font.sans-serif'] = [
    'WenQuanYi Micro Hei', 'SimHei', 'Arial Unicode MS'
]
plt.rcParams['axes.unicode_minus'] = False

# ================== 路径 ==================
img_path = "data/train_images/e32dc722eca5.png"
model_path = "/njzk/blindness/models/best_efficientnet_b3.pth"
save_dir = "figures"
os.makedirs(save_dir, exist_ok=True)

labels = [
    '无糖尿病视网膜病变',
    '轻度非增殖性DR',
    '中度非增殖性DR',
    '重度非增殖性DR',
    '增殖性DR（极重）'
]

device = 'cuda' if torch.cuda.is_available() else 'cpu'

# ================== 模型 ==================
model = timm.create_model(
    'efficientnet_b3',
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

# ================== 推理 ==================
with torch.no_grad():
    output = model(input_tensor)
    prob = torch.softmax(output, dim=1)[0].cpu().numpy()
    pred = output.argmax(1).item()

print(f"\n预测结果：{pred} → {labels[pred]}")
print(f"置信度：{prob[pred]*100:.2f}%")

# ================== Grad-CAM ==================
from pytorch_grad_cam import GradCAM
from pytorch_grad_cam.utils.model_targets import ClassifierOutputTarget

# ⭐ EfficientNet 正确层
target_layers = [model.conv_head]

cam = GradCAM(
    model=model,
    target_layers=target_layers,
    # use_cuda=(device == 'cuda')
)

targets = [ClassifierOutputTarget(pred)]
grayscale_cam = cam(
    input_tensor=input_tensor,
    targets=targets
)[0]

# ================== 论文级 CAM 后处理 ==================
cam_resized = cv2.resize(
    grayscale_cam,
    (img_rgb.shape[1], img_rgb.shape[0])
)

cam_resized = np.maximum(cam_resized, 0)
cam_resized = cam_resized / cam_resized.max()
cam_resized[cam_resized < 0.4] = 0  # ⭐ 关键

heatmap = cv2.applyColorMap(
    np.uint8(255 * cam_resized),
    cv2.COLORMAP_JET
)
heatmap = cv2.cvtColor(heatmap, cv2.COLOR_BGR2RGB)

overlay = img_rgb.copy()
mask = cam_resized > 0
overlay[mask] = (
    0.4 * img_rgb[mask] +
    0.6 * heatmap[mask]
).astype(np.uint8)

# ================== 可视化 ==================
plt.figure(figsize=(18, 8))

plt.subplot(1, 3, 1)
plt.imshow(img_rgb)
plt.title("原始眼底图像", fontsize=18)
plt.axis('off')

plt.subplot(1, 3, 2)
plt.imshow(cam_resized, cmap='jet')
plt.title("Grad-CAM 热力图", fontsize=18)
plt.axis('off')

plt.subplot(1, 3, 3)
plt.imshow(overlay)
plt.title(
    f"诊断结果：{pred}级 - {labels[pred]}\n"
    f"置信度：{prob[pred]*100:.1f}%",
    fontsize=18,
    color='red'
)
plt.axis('off')

plt.suptitle(
    "糖尿病视网膜病变智能辅助诊断系统",
    fontsize=24,
    fontweight='bold'
)

plt.tight_layout()
save_path = f"{save_dir}/GradCAM_EfficientNetB3_{pred}级.jpg"
plt.savefig(save_path, dpi=300, bbox_inches='tight')
plt.show()

print(f"\n✅ 已保存：{save_path}")
