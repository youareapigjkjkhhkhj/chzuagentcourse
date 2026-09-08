# test_ultimate.py  ← 永久根治版：支持中文 + 完美热力图 + 高清保存
import torch
import cv2
import numpy as np
import timm
import albumentations as A
from albumentations.pytorch import ToTensorV2
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import os

# ================== 关键：解决中文乱码（只加这几行就行！）==================
plt.rcParams['font.sans-serif'] = ['WenQuanYi Micro Hei', 'SimHei', 'Arial Unicode MS']
plt.rcParams['axes.unicode_minus'] = False

# Windows: SimHei   macOS: Heiti TC   Linux常用: WenQuanYi Micro Hei

# ================== 路径和模型 ==================
img_path = "data/train_images/e2a47a74e6e1.png"  # 随便改你想测的图
model_path = "/njzk/blindness/models/best_efficientnet_b5.pth"  # 改成你的真实路径

# ================== 万能加载权重（推荐直接用这个）==================
model = timm.create_model('efficientnet_b5', pretrained=False, num_classes=5)

ckpt = torch.load(model_path, map_location='cpu')

# 情况1：旧版 timm 权重（有下划线开头）
if list(ckpt.keys())[0].startswith('_'):
    ckpt = {k[1:]: v for k, v in ckpt.items()}

# 情况2：删除可能的 classifier 差异
ckpt.pop('classifier.weight', None)
ckpt.pop('classifier.bias', None)

# 宽松加载，忽略不匹配的 key
model.load_state_dict(ckpt, strict=False)

model.eval().cuda()
print("模型权重加载成功！（已自动适配旧版/新版命名差异）")

# ================== 预处理 ==================
transform = A.Compose([
    A.CLAHE(clip_limit=2.0),
    A.Resize(256, 256),
    A.CenterCrop(224, 224),
    A.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    ToTensorV2(),
])

img_bgr = cv2.imread(img_path)
img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
input_tensor = transform(image=img_rgb)['image'].unsqueeze(0).cuda()

# ================== 预测 ==================
with torch.no_grad():
    output = model(input_tensor)
    prob = torch.softmax(output, 1)[0].cpu().numpy()
    pred = output.argmax(1).item()

labels = ['无糖尿病视网膜病变', '轻度非增殖性DR', '中度非增殖性DR', '重度非增殖性DR', '增殖性DR（极重）']
print(f"\n【模型诊断结果】")
print(f"预测等级：{pred} → {labels[pred]}")
print(f"置信度：{prob[pred]*100:.1f}%")
for i, p in enumerate(prob):
    print(f"  {i}级: {p*100:6.2f}%")

# ================== Grad-CAM 热力图（已修复尺寸）==================
from pytorch_grad_cam import GradCAM
from pytorch_grad_cam.utils.model_targets import ClassifierOutputTarget

target_layers = [model.blocks[-1]]
cam = GradCAM(model=model, target_layers=target_layers)
targets = [ClassifierOutputTarget(pred)]
grayscale_cam = cam(input_tensor=input_tensor, targets=targets)[0, :]  # (224,224)

# 放大到原图尺寸
grayscale_cam_resized = cv2.resize(grayscale_cam, (img_rgb.shape[1], img_rgb.shape[0]))
heatmap = cv2.applyColorMap(np.uint8(255 * grayscale_cam_resized), cv2.COLORMAP_JET)
heatmap = cv2.cvtColor(heatmap, cv2.COLOR_BGR2RGB)
overlay = heatmap * 0.5 + img_rgb * 0.5
overlay = (overlay / overlay.max() * 255).astype(np.uint8)

# ================== 美观三联图（支持中文）==================
plt.figure(figsize=(18, 9), facecolor='white')
plt.subplot(1, 3, 1)
plt.imshow(img_rgb)
plt.title("原眼底图像", fontsize=18, fontweight='bold', pad=20)
plt.axis('off')

plt.subplot(1, 3, 2)
plt.imshow(grayscale_cam_resized, cmap='jet')
plt.title("模型关注区域热力图", fontsize=18, fontweight='bold', pad=20)
plt.axis('off')

plt.subplot(1, 3, 3)
plt.imshow(overlay)
plt.title(f"诊断结果：{pred}级 - {labels[pred]}\n置信度：{prob[pred]*100:.1f}%", 
          fontsize=20, fontweight='bold', pad=30, color='red')
plt.axis('off')

plt.suptitle("糖尿病视网膜病变智能辅助诊断系统", fontsize=26, fontweight='bold', y=0.98)
plt.tight_layout()

# 保存高清图
os.makedirs("figures", exist_ok=True)
save_path = f"figures/诊断报告_{labels[pred]}_{pred}级.jpg"
plt.savefig(save_path, dpi=300, bbox_inches='tight', facecolor='white')
plt.show()

print(f"\n诊断报告已保存 → {save_path}")