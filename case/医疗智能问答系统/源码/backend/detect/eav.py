# evaluate_all.py  ← 一键评估所有模型 + 出全套论文对比图！（6个CNN模型，不含ViT）
import os
import cv2
import torch
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.metrics import cohen_kappa_score, confusion_matrix, accuracy_score
from torch.utils.data import Dataset, DataLoader
from torch.cuda.amp import autocast
import timm
import albumentations as A
from albumentations.pytorch import ToTensorV2
from config import CFG
import time

# 中文字体
plt.rcParams['font.sans-serif'] = ['WenQuanYi Micro Hei', 'SimHei', 'Arial Unicode MS']
plt.rcParams['axes.unicode_minus'] = False
os.makedirs("figures", exist_ok=True)

class APTOSDataset(Dataset):
    def __init__(self, csv_file, img_dir, transform=None):
        self.df = pd.read_csv(csv_file)
        self.img_dir = img_dir
        self.transform = transform
    def __len__(self): return len(self.df)
    def __getitem__(self, idx):
        row = self.df.iloc[idx]
        img = cv2.imread(os.path.join(self.img_dir, row["id_code"]))
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        label = int(row["diagnosis"])
        if self.transform:
            img = self.transform(image=img)["image"]
        return img, label

transform = A.Compose([
    A.Resize(CFG.img_size, CFG.img_size),
    A.Normalize(mean=CFG.mean, std=CFG.std),
    ToTensorV2(),
])

dataset = APTOSDataset("../datasets/val.csv", "../datasets/train_images", transform)  # 使用验证集进行评估
loader = DataLoader(dataset, batch_size=64, shuffle=False, num_workers=0, pin_memory=True)  # 将num_workers设为0避免多进程问题

device = "cuda" if torch.cuda.is_available() else "cpu"

# 支持的模型映射（文件名包含关键词即可自动识别）
model_mapping = {
    "resnet50": "resnet50",
    "resnet152": "resnet152",
    "densenet121": "densenet121",
    "efficientnet_b3": "efficientnet_b3",
    "efficientnet_b5": "efficientnet_b5",
    "efficientnet_b8": "efficientnet_b8",
}

results = []

@torch.no_grad()
def evaluate_one(model_name, weight_path):
    print(f"\n正在评估: {model_name} ← {os.path.basename(weight_path)}")
    model = timm.create_model(model_name, pretrained=False, num_classes=5).to(device)
    state_dict = torch.load(weight_path, map_location=device)
    model.load_state_dict(state_dict)
    model.eval()

    # 推理速度测试（单张平均时间）
    start = time.time()
    dummy = torch.randn(1, 3, CFG.img_size, CFG.img_size).to(device)
    for _ in range(100): model(dummy)
    infer_time = (time.time() - start) / 100 * 1000  # ms

    # 预测
    preds, trues = [], []
    for imgs, labels in loader:
        imgs = imgs.to(device)
        with autocast():
            logits = model(imgs)
        preds.extend(logits.argmax(1).cpu().numpy())
        trues.extend(labels.numpy())

    acc = accuracy_score(trues, preds)
    qwk = cohen_kappa_score(trues, preds, weights="quadratic")
    cm = confusion_matrix(trues, preds)

    # 参数量
    params = sum(p.numel() for p in model.parameters()) / 1e6  # M

    results.append({
        "Model": model_name,
        "QWK": round(qwk, 4),
        "Accuracy": round(acc, 4),
        "Params(M)": round(params, 1),
        "Infer Time(ms)": round(infer_time, 1),
        "Confusion Matrix": cm
    })
    print(f"QWK: {qwk:.4f} | Acc: {acc:.4f} | Params: {params:.1f}M | Time: {infer_time:.1f}ms")

# 主程序
if __name__ == '__main__':
    # 自动扫描 train_model/ 目录下的子文件夹
    model_dir = "../train_model/"
    model_files = []
    
    # 递归扫描所有子文件夹
    for root, dirs, files in os.walk(model_dir):
        for file in files:
            if file.endswith('.pth') and 'best' in file:
                # 获取相对路径
                rel_path = os.path.relpath(os.path.join(root, file), '.')
                model_files.append(rel_path)
    
    print(f"找到 {len(model_files)} 个模型文件")
    
    # 评估每个模型
    for weight_path in model_files:
        # 从路径中提取模型名称
        dir_name = os.path.basename(os.path.dirname(weight_path))
        file_name = os.path.basename(weight_path)
        
        # 尝试从目录名或文件名中识别模型类型
        model_name = None
        for key in model_mapping.keys():
            if key in dir_name.lower() or key in file_name.lower():
                model_name = model_mapping[key]
                break
        
        if model_name:
            print(f"\n正在评估: {model_name} ← {file_name}")
            evaluate_one(model_name, weight_path)
        else:
            print(f"\n未识别的模型类型: {file_name}")
    
    # ===================== 生成论文对比图 =====================
    df = pd.DataFrame(results)
    df = df.sort_values("QWK", ascending=False)
    df.to_excel("figures/【七模型性能对比表】.xlsx", index=False)
    print("\n性能表格已保存: figures/【七模型性能对比表】.xlsx")
    print(df[["Model", "QWK", "Accuracy", "Params(M)", "Infer Time(ms)"]])

    # 1. 六宫格混淆矩阵
    n = len(results)
    cols = 3
    rows = (n + cols - 1) // cols
    plt.figure(figsize=(15, 5*rows))
    class_names = ['无', '轻度', '中度', '重度', '增殖性']
    for i, r in enumerate(results):
        plt.subplot(rows, cols, i+1)
        sns.heatmap(r["Confusion Matrix"], annot=True, fmt='d', cmap='Blues',
                    xticklabels=class_names, yticklabels=class_names)
        plt.title(f"{r['Model']}\nQWK={r['QWK']} Acc={r['Accuracy']}")
    plt.tight_layout()
    plt.savefig("figures/【六模型混淆矩阵对比】.jpg", dpi=300, bbox_inches='tight')
    plt.close()

    # 2. 雷达图（综合对比）
    from math import pi
    categories = ['QWK', 'Accuracy', 'Params(M)', 'Infer Time(ms)']
    labels = df['Model'].tolist()
    values = df[categories].values

    # 归一化（参数量和时间越小越好，取倒数）
    values[:, 2] = 1 / (values[:, 2] / values[:, 2].max())  # Params 倒数
    values[:, 3] = 1 / (values[:, 3] / values[:, 3].min())  # Time 倒数

    angles = [n / float(len(categories)) * 2 * pi for n in range(len(categories))]
    angles += angles[:1]

    fig, ax = plt.subplots(figsize=(10, 10), subplot_kw=dict(polar=True))
    for i, row in enumerate(values):
        row = np.append(row, row[0])
        ax.plot(angles, row, 'o-', linewidth=2, label=labels[i])
        ax.fill(angles, row, alpha=0.15)
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(categories)
    ax.set_title("六模型综合性能雷达图", fontsize=20, pad=20)
    ax.legend(loc='upper right', bbox_to_anchor=(1.3, 1.0))
    plt.savefig("figures/【六模型雷达图对比】.jpg", dpi=300, bbox_inches='tight')
    plt.close()

    print("\n所有论文对比图生成完毕！")
    print("→ figures/【六模型性能对比表】.xlsx")
    print("→ figures/【六模型混淆矩阵对比】.jpg")
    print("→ figures/【六模型雷达图对比】.jpg")
    print("\n所有模型评估完成！")