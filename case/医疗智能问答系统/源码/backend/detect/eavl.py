import os
import cv2
import torch
import torch.nn as nn
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.metrics import cohen_kappa_score, classification_report, confusion_matrix
from torch.utils.data import Dataset, DataLoader
from  torch import amp
import albumentations as A
from albumentations.pytorch import ToTensorV2
from albumentations import (
    Compose, Resize, Normalize
)
import timm
from config import CFG
plt.rcParams['font.sans-serif'] = ['WenQuanYi Micro Hei', 'SimHei', 'Arial Unicode MS']
plt.rcParams['axes.unicode_minus'] = False
# ===================== Dataset =====================
class APTOSDataset(Dataset):
    def __init__(self, csv_file, img_dir, transform=None):
        self.df = pd.read_csv(csv_file)
        self.img_dir = img_dir
        self.transform = transform

    def __len__(self):
        return len(self.df)

    def __getitem__(self, idx):
        row = self.df.iloc[idx]
        img_path = os.path.join(self.img_dir, row["id_code"])
        img = cv2.imread(img_path)

        if img is None:
            raise RuntimeError(f"Image not found: {img_path}")

        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        label = int(row["diagnosis"])

        if self.transform:
            img = self.transform(image=img)["image"]

        return img, label

# ===================== Model =====================
def create_model(model_name, pretrained_path=None, num_classes=5):
    model = timm.create_model(model_name, pretrained=False, num_classes=num_classes)
    
    if pretrained_path is not None and os.path.exists(pretrained_path):
        print(f"Loading model weights from {pretrained_path}")
        state_dict = torch.load(pretrained_path, map_location='cpu')
        model.load_state_dict(state_dict)
        print("Model weights loaded successfully.")
    
    return model

# ===================== Evaluation =====================
def evaluate_model(model, loader, device):
    model.eval()
    all_preds = []
    all_labels = []
    
    with torch.no_grad():
        for imgs, labels in loader:
            imgs = imgs.to(device)
            from torch.amp import autocast
            with amp.autocast("cuda"):
                logits = model(imgs)
            
            preds = torch.argmax(logits, dim=1)
            all_preds.extend(preds.cpu().numpy())
            all_labels.extend(labels.numpy())
    
    return np.array(all_labels), np.array(all_preds)

# ===================== Main =====================
def main(model_name, model_path):
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Using: {device}")
    
    # 数据预处理
    val_transform = Compose([
        Resize(CFG.img_size, CFG.img_size),
        Normalize(mean=CFG.mean, std=CFG.std),
        ToTensorV2(),
    ])
    
    # 加载数据集
    val_dataset = APTOSDataset("../datasets/val.csv", CFG.train_img_dir, val_transform)
    val_loader = DataLoader(val_dataset, batch_size=CFG.batch_size, shuffle=False)
    
    # 加载模型
    model = create_model(model_name, model_path).to(device)
    
    # 评估模型
    true_labels, pred_labels = evaluate_model(model, val_loader, device)
    
    # 计算指标
    accuracy = (true_labels == pred_labels).mean()
    kappa = cohen_kappa_score(true_labels, pred_labels, weights="quadratic")
    
    print(f"\n模型: {model_name}")
    print(f"验证集准确率: {accuracy:.4f} ({accuracy*100:.2f}%)")
    print(f"加权Kappa系数: {kappa:.4f}")
    
    # 分类报告
    class_names = ['无', '轻度', '中度', '重度', '增殖性']
    print("\n分类报告:")
    print(classification_report(true_labels, pred_labels, target_names=class_names))
    
    # 混淆矩阵
    cm = confusion_matrix(true_labels, pred_labels)
    plt.figure(figsize=(10, 8))
    sns.heatmap(cm, annot=True, fmt='d', cmap='Blues', 
                xticklabels=class_names, yticklabels=class_names)
    plt.title('混淆矩阵')
    plt.xlabel('预测标签')
    plt.ylabel('真实标签')
    plt.savefig(f'confusion_matrix_{model_name}.png')
    print(f"\n混淆矩阵已保存为: confusion_matrix_{model_name}.png")
    
    # 按类别分析准确率
    print("\n各类别准确率:")
    for i, class_name in enumerate(class_names):
        class_mask = (true_labels == i)
        if class_mask.sum() > 0:
            class_acc = (true_labels[class_mask] == pred_labels[class_mask]).mean()
            print(f"类别 {i} ({class_name}): {class_acc:.4f} ({class_acc*100:.2f}%)")
    
    # 显示一些错误预测的例子
    error_indices = np.where(true_labels != pred_labels)[0]
    error_count = len(error_indices)
    total_count = len(true_labels)
    error_rate = error_count / total_count * 100
    
    print(f"\n错误预测总数: {error_count}/{total_count} ({error_rate:.2f}%)")
    
    if error_count > 0:
        print(f"\n错误预测示例 (显示前10个):")
        for i, idx in enumerate(error_indices[:10]):
            true_label = true_labels[idx]
            pred_label = pred_labels[idx]
            img_id = val_dataset.df.iloc[idx]["id_code"]
            print(f"{i+1}. 图片 {img_id}: 真实={true_label}({class_names[true_label]}), 预测={pred_label}({class_names[pred_label]})")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='评估模型在验证集上的性能')
    parser.add_argument('--model', type=str, required=True,
                        choices=["resnet50","resnet152","densenet121","efficientnet_b8",
                                 "efficientnet_b3","efficientnet_b5"])
    parser.add_argument('--model_path', type=str, required=True,
                        help='训练好的模型权重路径')
    args = parser.parse_args()
    
    main(args.model, args.model_path)