import os
import cv2
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
from torch.cuda.amp import autocast, GradScaler

import timm
import albumentations as A
from albumentations.pytorch import ToTensorV2
from albumentations import (
    Compose, RandomResizedCrop, HorizontalFlip,
    RandomBrightnessContrast, CLAHE, Resize, CenterCrop, Normalize
)
from albumentations.pytorch import ToTensorV2

import pandas as pd
import numpy as np
from sklearn.metrics import cohen_kappa_score

from confi1 import CFG


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


# ===================== Data Aug =====================
def get_transforms(train=True):
    if train:
        return Compose([
            # RandomResizedCrop：新版必须加 size
            RandomResizedCrop(size=(CFG.img_size, CFG.img_size), scale=(0.85,1.0)),
            HorizontalFlip(p=0.5),
            RandomBrightnessContrast(p=0.4),
            CLAHE(clip_limit=2.0, p=0.8),
            Normalize(mean=CFG.mean, std=CFG.std),
            ToTensorV2(),
        ])
    else:
        return Compose([
            Resize(CFG.img_size, CFG.img_size),
            Normalize(mean=CFG.mean, std=CFG.std),
            ToTensorV2(),
        ])



# ===================== Model =====================
def create_model(model_name, pretrained_path=None, num_classes=5):
    # 不联网下载，先创建模型
    model = timm.create_model(model_name, pretrained=False, num_classes=num_classes)
    
    if pretrained_path is not None and os.path.exists(pretrained_path):
        # 加载本地预训练权重
        print(f"Loading pretrained weights from {pretrained_path}")
        state_dict = torch.load(pretrained_path, map_location='cpu')
        
        # 删除分类头权重
        state_dict.pop('classifier.weight', None)
        state_dict.pop('classifier.bias', None)
        
        # 加载剩余权重，strict=False 忽略缺失或多余键
        model.load_state_dict(state_dict, strict=False)
        print("Pretrained weights loaded, classifier randomly initialized.")
    
    return model


# ===================== Train One Epoch =====================
def train_one_epoch(model, loader, optimizer, scaler, criterion, device):
    model.train()
    total_loss = 0

    for imgs, labels in loader:
        imgs, labels = imgs.to(device), labels.to(device)

        optimizer.zero_grad()
        from torch import amp
        # 新写法
        with amp.autocast(device_type="cuda"):
            logits = model(imgs)
            loss = criterion(logits, labels)

        scaler.scale(loss).backward()
        scaler.step(optimizer)
        scaler.update()

        total_loss += loss.item()

    return total_loss / len(loader)

# ===================== Validate =====================
def validate(model, loader, criterion, device):
    model.eval()
    preds, labels_list = [], []
    total_loss = 0

    with torch.no_grad():
        for imgs, labels in loader:
            imgs, labels = imgs.to(device), labels.to(device)
            from torch import amp
            with amp.autocast(device_type="cuda"):
                logits = model(imgs)
                loss = criterion(logits, labels)

            total_loss += loss.item()
            pred = logits.argmax(1)

            preds.extend(pred.cpu().numpy())
            labels_list.extend(labels.cpu().numpy())

    kappa = cohen_kappa_score(labels_list, preds, weights="quadratic")
    acc = (np.array(preds) == np.array(labels_list)).mean()

    return total_loss / len(loader), kappa, acc


# ===================== Main Train Loop =====================
import matplotlib.pyplot as plt
# ===================== Main Train Loop =====================
def main(model_name):
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print("Using:", device)
    # Dataset & Loader
    train_ds = APTOSDataset("dataset/train.csv", CFG.train_img_dir, get_transforms(train=True))
    val_ds = APTOSDataset("dataset/val.csv", CFG.train_img_dir, get_transforms(train=False))
    train_loader = DataLoader(train_ds, batch_size=CFG.batch_size, shuffle=True,
                              num_workers=6, pin_memory=True, drop_last=True)
    val_loader = DataLoader(val_ds, batch_size=CFG.batch_size * 2, shuffle=False,
                            num_workers=6, pin_memory=True)
    # Model
    model = create_model(model_name=args.model, pretrained_path=args.pretrained_path).to(device)
    # Class weight
    freq = torch.tensor(CFG.class_freq, dtype=torch.float32)
    weights = (1.0 / freq)
    weights = weights / weights.sum() * len(freq)
    weights = weights.to(device)
    criterion = nn.CrossEntropyLoss(weight=weights)
    optimizer = optim.AdamW(model.parameters(), lr=CFG.lr, weight_decay=CFG.weight_decay)
    scheduler = optim.lr_scheduler.CosineAnnealingWarmRestarts(optimizer, T_0=10)
    from torch import amp
    scaler = amp.GradScaler()
    best_kappa = -999

    os.makedirs("models", exist_ok=True)

    # 根据 model_name 创建独立 figures 文件夹
    figures_dir = os.path.join("figures", model_name)
    os.makedirs(figures_dir, exist_ok=True)

    # 用于可视化
    train_losses, val_losses, kappas, accs = [], [], [], []

    # Training loop
    for epoch in range(1, CFG.epochs + 1):
        train_loss = train_one_epoch(model, train_loader, optimizer, scaler, criterion, device)
        val_loss, kappa, acc = validate(model, val_loader, criterion, device)
        scheduler.step()

        train_losses.append(train_loss)
        val_losses.append(val_loss)
        kappas.append(kappa)
        accs.append(acc)

        print(f"[Epoch {epoch}] "
              f"Train Loss: {train_loss:.4f} | Val Loss: {val_loss:.4f} | "
              f"Kappa: {kappa:.4f} | Acc: {acc:.4f}")

        # Save best model
        if kappa > best_kappa:
            best_kappa = kappa
            torch.save(model.state_dict(), f"models/best_{model_name}.pth")
            print(f"������ Saved best model (kappa={best_kappa:.4f})")

        # 绘制训练曲线并保存
        plt.figure(figsize=(10,4))
        plt.subplot(1,2,1)
        plt.plot(range(1, epoch+1), train_losses, label="Train Loss")
        plt.plot(range(1, epoch+1), val_losses, label="Val Loss")
        plt.xlabel("Epoch")
        plt.ylabel("Loss")
        plt.title("Loss Curve")
        plt.legend()

        plt.subplot(1,2,2)
        plt.plot(range(1, epoch+1), kappas, label="Kappa")
        plt.plot(range(1, epoch+1), accs, label="Accuracy")
        plt.xlabel("Epoch")
        plt.ylabel("Score")
        plt.title("Kappa & Accuracy")
        plt.legend()

        plt.tight_layout()
        plt.savefig(os.path.join(figures_dir, f"train_val_epoch_{epoch}.png"))
        plt.close()

    # 最终保存整体训练曲线
    plt.figure(figsize=(10,4))
    plt.subplot(1,2,1)
    plt.plot(range(1, CFG.epochs+1), train_losses, label="Train Loss")
    plt.plot(range(1, CFG.epochs+1), val_losses, label="Val Loss")
    plt.xlabel("Epoch")
    plt.ylabel("Loss")
    plt.title("Loss Curve")
    plt.legend()

    plt.subplot(1,2,2)
    plt.plot(range(1, CFG.epochs+1), kappas, label="Kappa")
    plt.plot(range(1, CFG.epochs+1), accs, label="Accuracy")
    plt.xlabel("Epoch")
    plt.ylabel("Score")
    plt.title("Kappa & Accuracy")
    plt.legend()

    plt.tight_layout()
    plt.savefig(os.path.join(figures_dir, "final_train_val_curve.png"))
    plt.close()

    print(f"Training done. All figures saved in '{figures_dir}/'")


# ================ Entry ================
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=str, required=True,
                    choices=["resnet50","densenet121","efficientnet_b0",
                             "efficientnet_b3","efficientnet_b5","efficientnet_b8","vit_base_patch16_224"])
    parser.add_argument("--pretrained_path", type=str, default=None,
                    help="本地预训练权重路径，例如 models/pre/efficientnet_b3-c3c993c0.pth")
    args = parser.parse_args()
    main(args.model)
