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
from torch.cuda.amp import autocast
import albumentations as A
from albumentations.pytorch import ToTensorV2
from albumentations import Compose, Resize, Normalize
import timm
from datetime import datetime

# ===================== 中文支持 =====================
plt.rcParams['font.sans-serif'] = ['WenQuanYi Micro Hei', 'SimHei', 'Arial Unicode MS', 'DejaVu Sans']
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
        img_path = os.path.join(self.img_dir, row["id_code"])  # 注意：很多数据集图片是 .png
        img = cv2.imread(img_path)
        if img is None:
            raise RuntimeError(f"Image not found or cannot be read: {img_path}")
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        label = int(row["diagnosis"])

        if self.transform:
            augmented = self.transform(image=img)
            img = augmented["image"]

        return img, label


# ===================== 万能模型加载（关键修复）=====================
def create_model(model_name, pretrained_path=None, num_classes=5):
    model = timm.create_model(model_name, pretrained=False, num_classes=num_classes)

    if pretrained_path is not None and os.path.exists(pretrained_path):
        print(f"正在从 {pretrained_path} 加载模型权重...")
        ckpt = torch.load(pretrained_path, map_location='cpu')

        # 情况1：旧版 timm 权重（key 以 '_' 开头，如 _conv_stem）
        if list(ckpt.keys())[0].startswith('_'):
            print("检测到旧版 timm 权重命名，正在自动去除前缀 '_' ...")
            ckpt = {k[1:]: v for k, v in ckpt.items()}

        # 情况2：移除可能不匹配的 classifier 头
        ckpt.pop('classifier.weight', None)
        ckpt.pop('classifier.bias', None)

        # 宽松加载（推荐）
        missing_keys, unexpected_keys = model.load_state_dict(ckpt, strict=False)

        if missing_keys:
            print(f"缺失键（通常是新的分类器头，已自动随机初始化）: {len(missing_keys)} 个")
        if unexpected_keys:
            print(f"多余键（已被忽略）: {len(unexpected_keys)} 个")

        print("模型权重加载成功！")
    else:
        print("未提供权重路径，使用随机初始化的模型（仅用于测试代码）")

    return model


# ===================== Evaluation =====================
def evaluate_model(model, loader, device):
    model.eval()
    all_preds = []
    all_labels = []

    with torch.no_grad():
        for imgs, labels in loader:
            imgs = imgs.to(device)
            labels = labels.to(device)

            with autocast():
                logits = model(imgs)

            preds = torch.argmax(logits, dim=1)
            all_preds.extend(preds.cpu().numpy())
            all_labels.extend(labels.cpu().numpy())

    return np.array(all_labels), np.array(all_preds)


# ===================== Main =====================
def main(model_name, model_path):
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"使用设备: {device}")

    # ===================== 数据预处理 =====================
    # 请确保你的 config.py 中有 CFG.img_size, CFG.mean, CFG.std, CFG.train_img_dir, CFG.batch_size
    # 如果没有 config，可以直接在这里硬编码
    try:
        from config import CFG
        img_size = CFG.img_size
        mean = CFG.mean
        std = CFG.std
        train_img_dir = CFG.train_img_dir
        batch_size = CFG.batch_size
    except:
        print("未找到 config.py，使用默认值")
        img_size = 224
        mean = [0.485, 0.456, 0.406]
        std = [0.229, 0.224, 0.225]
        train_img_dir = "./data/train_images"  # 请改成你的实际路径
        batch_size = 32

    val_transform = Compose([
        Resize(img_size, img_size),
        Normalize(mean=mean, std=std),
        ToTensorV2(),
    ])

    # ===================== 加载数据集 =====================
    val_dataset = APTOSDataset("./dataset/val.csv", train_img_dir, val_transform)
    val_loader = DataLoader(val_dataset, batch_size=batch_size, shuffle=False, num_workers=4, pin_memory=True)

    # ===================== 加载模型 =====================
    model = create_model(model_name, model_path, num_classes=5).to(device)

    # ===================== 评估 =====================
    true_labels, pred_labels = evaluate_model(model, val_loader, device)

    # 计算指标
    accuracy = (true_labels == pred_labels).mean()
    kappa = cohen_kappa_score(true_labels, pred_labels, weights="quadratic")

    print(f"\n=== 模型评估结果 ===")
    print(f"模型名称: {model_name}")
    print(f"验证集准确率: {accuracy:.4f} ({accuracy*100:.2f}%)")
    print(f"二次加权 Kappa: {kappa:.4f}")

    # 分类报告
    class_names = ['无糖尿病视网膜病变', '轻度', '中度', '重度', '增殖性DR']
    print("\n详细分类报告:")
    print(classification_report(true_labels, pred_labels, target_names=class_names))

    # 混淆矩阵
    cm = confusion_matrix(true_labels, pred_labels)
    plt.figure(figsize=(10, 8))
    sns.heatmap(cm, annot=True, fmt='d', cmap='Blues',
                xticklabels=class_names, yticklabels=class_names)
    plt.title('混淆矩阵', fontsize=16)
    plt.xlabel('预测标签')
    plt.ylabel('真实标签')

    # 保存带时间戳的图片，避免覆盖
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    cm_path = f"confusion_matrix_{model_name}_{timestamp}.png"
    plt.savefig(cm_path, dpi=300, bbox_inches='tight')
    plt.show()
    print(f"\n混淆矩阵已保存: {cm_path}")

    # 各类别准确率
    print("\n各类别准确率:")
    for i, class_name in enumerate(class_names):
        mask = (true_labels == i)
        if mask.sum() > 0:
            acc = (pred_labels[mask] == i).mean()
            print(f"  {i} - {class_name}: {acc:.4f} ({acc*100:.2f}%)  (样本数: {mask.sum()})")

    # 错误预测示例
    error_indices = np.where(true_labels != pred_labels)[0]
    if len(error_indices) > 0:
        print(f"\n发现 {len(error_indices)} 个错误预测，前10个示例:")
        for i, idx in enumerate(error_indices[:10]):
            true = true_labels[idx]
            pred = pred_labels[idx]
            img_id = val_dataset.df.iloc[idx]["id_code"]
            print(f"  {i+1}. {img_id}.png → 真实: {true}({class_names[true]})  预测: {pred}({class_names[pred]})")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='评估糖尿病视网膜病变模型在验证集上的性能')
    parser.add_argument('--model', type=str, required=True,
                        choices=["resnet50", "resnet152", "densenet121", "efficientnet_b3",
                                 "efficientnet_b5", "efficientnet_b8", "vit_base_patch16_224"],
                        help='模型名称')
    parser.add_argument('--model_path', type=str, required=True,
                        help='训练好的 .pth 权重文件路径')
    args = parser.parse_args()

    main(args.model, args.model_path)