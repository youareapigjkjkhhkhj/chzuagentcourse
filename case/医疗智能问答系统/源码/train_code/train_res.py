import os
import cv2
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
from torch.amp import autocast, GradScaler
from torch.nn import functional as F

import timm
import albumentations as A
from albumentations.pytorch import ToTensorV2
from albumentations import (
    Compose, RandomResizedCrop, HorizontalFlip, VerticalFlip,
    RandomBrightnessContrast, CLAHE, Resize, CenterCrop, Normalize,
    RandomRotate90, OneOf, GridDropout, CoarseDropout, GaussianBlur
)
from albumentations.pytorch import ToTensorV2

import pandas as pd
import numpy as np
from sklearn.metrics import cohen_kappa_score
from tqdm import tqdm

from config import CFG


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
            # 创建虚拟图像避免训练中断
            img = np.zeros((224, 224, 3), dtype=np.uint8)
            print(f"Warning: Image not found: {img_path}")

        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        label = int(row["diagnosis"])

        if self.transform:
            img = self.transform(image=img)["image"]

        return img, label


# ===================== 强化的数据增强 =====================
def get_strong_transforms(train=True):
    if train:
        return Compose([
            # 基础裁剪和缩放
            RandomResizedCrop(size=(CFG.img_size, CFG.img_size), scale=(0.8, 1.0)),
            
            # 多角度旋转和翻转
            OneOf([
                HorizontalFlip(p=1.0),
                VerticalFlip(p=1.0),
                RandomRotate90(p=1.0),
            ], p=0.5),
            
            # 颜色和光照增强
            OneOf([
                RandomBrightnessContrast(brightness_limit=0.2, contrast_limit=0.2, p=1.0),
                CLAHE(clip_limit=2.0, p=1.0),
                GaussianBlur(blur_limit=3, p=1.0),
            ], p=0.4),
            
            # 空间变换
            OneOf([
                GridDropout(ratio=0.1, p=1.0),
                CoarseDropout(max_holes=8, hole_size=(32, 32), p=1.0),
            ], p=0.3),
            
            # 标准化
            Normalize(mean=CFG.mean, std=CFG.std),
            ToTensorV2(),
        ])
    else:
        return Compose([
            Resize(CFG.img_size, CFG.img_size),
            Normalize(mean=CFG.mean, std=CFG.std),
            ToTensorV2(),
        ])


# ===================== 添加Dropout的模型包装 =====================
class ModelWithDropout(nn.Module):
    def __init__(self, backbone, dropout_rate=0.5):
        super().__init__()
        self.backbone = backbone
        self.dropout = nn.Dropout(dropout_rate)
        
        # 如果是ResNet，需要添加dropout到classifier前
        if hasattr(backbone, 'classifier'):
            # EfficientNet
            original_classifier = backbone.classifier
            backbone.classifier = nn.Sequential(
                nn.Dropout(dropout_rate),
                original_classifier
            )
        elif hasattr(backbone, 'head'):
            # Vision Transformer
            original_head = backbone.head
            backbone.head = nn.Sequential(
                nn.Dropout(dropout_rate),
                original_head
            )
        elif hasattr(backbone, 'fc'):
            # ResNet
            original_fc = backbone.fc
            backbone.fc = nn.Sequential(
                nn.Dropout(dropout_rate),
                original_fc
            )
    
    def forward(self, x):
        return self.dropout(self.backbone(x))


# ===================== 优化的训练函数 =====================
def train_one_epoch(model, loader, optimizer, scaler, criterion, device, grad_clip=1.0):
    model.train()
    total_loss = 0
    
    pbar = tqdm(loader, desc="Training")
    for imgs, labels in pbar:
        imgs, labels = imgs.to(device), labels.to(device)

        optimizer.zero_grad()
        
        with torch.amp.autocast('cuda'):
            logits = model(imgs)
            loss = criterion(logits, labels)

        scaler.scale(loss).backward()
        
        # 梯度裁剪
        scaler.unscale_(optimizer)
        torch.nn.utils.clip_grad_norm_(model.parameters(), grad_clip)
        
        scaler.step(optimizer)
        scaler.update()

        total_loss += loss.item()
        pbar.set_postfix({'loss': f'{loss.item():.4f}'})

    return total_loss / len(loader)


# ===================== 验证函数 =====================
def validate(model, loader, criterion, device):
    model.eval()
    preds, labels_list = [], []
    total_loss = 0

    with torch.no_grad():
        for imgs, labels in tqdm(loader, desc="Validating"):
            imgs, labels = imgs.to(device), labels.to(device)
            
            with torch.amp.autocast('cuda'):
                logits = model(imgs)
                loss = criterion(logits, labels)

            total_loss += loss.item()
            pred = logits.argmax(1)

            preds.extend(pred.cpu().numpy())
            labels_list.extend(labels.cpu().numpy())

    kappa = cohen_kappa_score(labels_list, preds, weights="quadratic")
    acc = (np.array(preds) == np.array(labels_list)).mean()

    return total_loss / len(loader), kappa, acc


# ===================== 增强的早停类 =====================
class EnhancedEarlyStopping:
    def __init__(self, patience=50, min_delta=0.001, restore_best_weights=True, verbose=True, min_epochs=50):
        self.patience = patience
        self.min_delta = min_delta
        self.restore_best_weights = restore_best_weights
        self.verbose = verbose
        self.min_epochs = min_epochs  # 最少训练轮数
        
        self.best_loss = float('inf')
        self.counter = 0
        self.best_weights = None
        self.last_improvement = 0
        
    def __call__(self, val_loss, val_kappa, epoch, model):
        # 在最少训练轮数之前，不触发早停
        if epoch < self.min_epochs:
            # 仍然记录最佳损失，但不增加计数器
            if val_loss < self.best_loss - self.min_delta:
                self.best_loss = val_loss
                self.last_improvement = epoch
                if self.restore_best_weights:
                    self.best_weights = model.state_dict().copy()
                
                if self.verbose:
                    print(f"✅ New best val loss: {val_loss:.4f} (Epoch {epoch})")
            return False
        
        # 超过最少训练轮数后，开始正常早停逻辑
        if val_loss < self.best_loss - self.min_delta:
            self.best_loss = val_loss
            self.counter = 0
            self.last_improvement = epoch
            if self.restore_best_weights:
                self.best_weights = model.state_dict().copy()
            
            if self.verbose:
                print(f"✅ New best val loss: {val_loss:.4f} (Epoch {epoch})")
        else:
            self.counter += 1
            
        # 过拟合检测：损失上升但Kappa下降更严重
        if self.counter >= 10:  # 提前警告
            if self.verbose and epoch > self.last_improvement + 5:
                print(f"⚠️ Warning: No improvement for {self.counter} epochs")
        
        # 正式早停
        if self.counter >= self.patience:
            if self.restore_best_weights and self.best_weights is not None:
                model.load_state_dict(self.best_weights)
                if self.verbose:
                    print(f"������ Early stopping: No improvement for {self.patience} epochs")
                    print(f"Restored best model (val_loss: {self.best_loss:.4f})")
            return True
        return False


# ===================== 验证损失上升幅度监控类 =====================
class ValLossIncreaseDetector:
    def __init__(self, window_size=3, large_increase_threshold=0.1, moderate_increase_threshold=0.05):
        self.window_size = window_size
        self.large_increase_threshold = large_increase_threshold  # 大幅度上升阈值
        self.moderate_increase_threshold = moderate_increase_threshold  # 中等上升阈值
        self.val_loss_history = []
        self.increase_count = 0
        
    def update(self, val_loss, epoch):
        """更新验证损失历史并检测上升幅度"""
        self.val_loss_history.append(val_loss)
        
        # 保持固定窗口大小
        if len(self.val_loss_history) > self.window_size:
            self.val_loss_history = self.val_loss_history[-self.window_size:]
        
        if len(self.val_loss_history) < 2:
            return "normal", 0.0
        
        # 计算最近两次的上升幅度
        recent_increase = val_loss - self.val_loss_history[-2]
        
        # 分类上升幅度
        if recent_increase >= self.large_increase_threshold:
            self.increase_count += 1
            return "large_increase", recent_increase
        elif recent_increase >= self.moderate_increase_threshold:
            self.increase_count += 1
            return "moderate_increase", recent_increase
        else:
            self.increase_count = 0
            return "normal", recent_increase
    
    def get_increase_severity(self):
        """获取上升严重程度"""
        if self.increase_count >= 3:
            return "severe"  # 连续3次中等或1次大幅度上升
        elif self.increase_count >= 2:
            return "moderate"  # 连续2次中等上升
        elif self.increase_count >= 1:
            return "mild"  # 1次中等上升
        else:
            return "none"
    
    def reset(self):
        """重置计数器"""
        self.increase_count = 0


# ===================== 过拟合检测类 =====================
class OverfittingDetector:
    def __init__(self, window_size=5, patience=3):
        self.window_size = window_size
        self.patience = patience
        self.overfitting_count = 0
        self.history = {
            'train_loss': [],
            'val_loss': [],
            'val_kappa': []
        }
    
    def update(self, train_loss, val_loss, val_kappa):
        """更新监控数据"""
        self.history['train_loss'].append(train_loss)
        self.history['val_loss'].append(val_loss)
        self.history['val_kappa'].append(val_kappa)
        
        # 保持固定窗口大小
        if len(self.history['train_loss']) > self.window_size * 2:
            for key in self.history:
                self.history[key] = self.history[key][-self.window_size:]
        
        return self._check_overfitting()
    
    def _check_overfitting(self):
        """检测过拟合"""
        if len(self.history['train_loss']) < self.window_size:
            return False, "Insufficient data"
        
        # 获取最近的数据窗口
        recent_train = self.history['train_loss'][-self.window_size:]
        recent_val = self.history['val_loss'][-self.window_size:]
        recent_kappa = self.history['val_kappa'][-self.window_size:]
        
        # 检测模式1: 训练损失下降，验证损失上升
        train_trend = recent_train[-1] - recent_train[0]
        val_trend = recent_val[-1] - recent_val[0]
        
        # 检测模式2: Kappa下降
        kappa_trend = recent_kappa[-1] - recent_kappa[0]
        
        # 过拟合条件
        is_overfitting = (
            train_trend < -0.01 and val_trend > 0.01  # 损失背离
        ) or (
            kappa_trend < -0.02  # 性能下降
        )
        
        if is_overfitting:
            self.overfitting_count += 1
        else:
            self.overfitting_count = 0
        
        # 连续检测到过拟合才报警
        if self.overfitting_count >= self.patience:
            self.overfitting_count = 0
            return True, f"Overfitting detected: train_loss_trend={train_trend:.3f}, val_loss_trend={val_trend:.3f}, kappa_trend={kappa_trend:.3f}"
        
        return False, "Normal"


# ===================== 主要训练循环 =====================
import matplotlib.pyplot as plt

def main(model_name, pretrained_path=None):
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Using device: {device}")
    
    # 数据加载
    train_ds = APTOSDataset("dataset/train.csv", CFG.train_img_dir, get_strong_transforms(train=True))
    val_ds = APTOSDataset("dataset/val.csv", CFG.train_img_dir, get_strong_transforms(train=False))
    
    train_loader = DataLoader(train_ds, batch_size=CFG.batch_size, shuffle=True,
                              num_workers=4, pin_memory=True, drop_last=True)
    val_loader = DataLoader(val_ds, batch_size=CFG.batch_size * 2, shuffle=False,
                            num_workers=4, pin_memory=True)
    
    print(f"Train size: {len(train_ds)}, Val size: {len(val_ds)}")
    
    # 模型创建
    backbone = create_model(model_name, pretrained_path)
    model = ModelWithDropout(backbone, CFG.dropout_rate).to(device)
    
    # 类别权重
    freq = torch.tensor(CFG.class_freq, dtype=torch.float32)
    weights = (1.0 / freq)
    weights = weights / weights.sum() * len(freq)
    weights = weights.to(device)
    criterion = nn.CrossEntropyLoss(weight=weights)
    
    # 优化器和调度器
    optimizer = optim.AdamW(model.parameters(), lr=CFG.lr, weight_decay=CFG.weight_decay)
    scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode='max', factor=0.5, patience=5)
    
    scaler = torch.amp.GradScaler('cuda')
    
    # 增强的早停机制（50轮最少训练保障）
    early_stopping = EnhancedEarlyStopping(patience=15, min_delta=0.001, verbose=True, min_epochs=50)
    
    # 验证损失上升检测器
    val_loss_detector = ValLossIncreaseDetector(window_size=3, large_increase_threshold=0.1, moderate_increase_threshold=0.05)
    
    # 过拟合检测器
    overfitting_detector = OverfittingDetector(window_size=5, patience=3)
    
    best_kappa = -999
    os.makedirs("models", exist_ok=True)
    os.makedirs("figures", exist_ok=True)
    
    # 记录训练过程
    train_losses, val_losses, kappas, accs = [], [], [], []
    lrs = []
    
    # 创建按模型分类的保存目录
    model_figures_dir = os.path.join("figures", model_name)
    os.makedirs(model_figures_dir, exist_ok=True)
    
    print(f"Starting training {model_name}...")
    
    # 初始化过拟合检测消息
    overfitting_msg = "Normal"
    
    for epoch in range(1, CFG.epochs + 1):
        print(f"\nEpoch {epoch}/{CFG.epochs}")
        
        # 训练
        train_loss = train_one_epoch(model, train_loader, optimizer, scaler, criterion, 
                                   device, CFG.grad_clip)
        
        # 验证
        val_loss, kappa, acc = validate(model, val_loader, criterion, device)
        
        # 验证损失上升检测
        increase_severity, increase_amount = val_loss_detector.update(val_loss, epoch)
        if increase_severity != "normal":
            print(f"⚠️ 验证损失上升检测: {increase_severity} (上升幅度: {increase_amount:.4f})")
        
        # 过拟合检测
        is_overfitting, overfitting_msg = overfitting_detector.update(train_loss, val_loss, kappa)
        if is_overfitting:
            print(f"������ {overfitting_msg}")
            # 可以在这里添加额外的正则化措施，比如增加dropout率
            if hasattr(model, 'dropout') and model.dropout.p < 0.7:
                print(f"Increasing dropout rate: {model.dropout.p:.2f} → 0.7")
                model.dropout.p = 0.7
        
        # 处理验证损失大幅上升（保障50轮训练期间）
        if increase_severity == "large_increase":
            print(f"������ 检测到验证损失大幅上升，增加正则化强度...")
            # 动态增加dropout率
            if hasattr(model, 'dropout') and model.dropout.p < 0.8:
                new_dropout = min(0.8, model.dropout.p + 0.1)
                print(f"动态调整dropout率: {model.dropout.p:.2f} → {new_dropout:.2f}")
                model.dropout.p = new_dropout
            
            # 动态增加权重衰减
            current_weight_decay = optimizer.param_groups[0]['weight_decay']
            new_weight_decay = min(1.0, current_weight_decay * 1.5)
            optimizer.param_groups[0]['weight_decay'] = new_weight_decay
            print(f"动态调整权重衰减: {current_weight_decay:.3f} → {new_weight_decay:.3f}")
            
        elif increase_severity == "moderate_increase":
            print(f"������ 检测到验证损失中等上升，增加轻度正则化...")
            # 轻微增加dropout率
            if hasattr(model, 'dropout') and model.dropout.p < 0.6:
                new_dropout = min(0.6, model.dropout.p + 0.05)
                print(f"轻度调整dropout率: {model.dropout.p:.2f} → {new_dropout:.2f}")
                model.dropout.p = new_dropout
        
        # 学习率调度
        scheduler.step(kappa)
        current_lr = optimizer.param_groups[0]['lr']
        lrs.append(current_lr)
        
        # 记录
        train_losses.append(train_loss)
        val_losses.append(val_loss)
        kappas.append(kappa)
        accs.append(acc)
        
        print(f"[Epoch {epoch}] Train Loss: {train_loss:.4f} | Val Loss: {val_loss:.4f} | "
              f"Kappa: {kappa:.4f} | Acc: {acc:.4f} | LR: {current_lr:.2e} | {overfitting_msg}")
        
        try:
            # 保存最佳模型
            if kappa > best_kappa:
                best_kappa = kappa
                torch.save(model.state_dict(), f"models/best_{model_name}.pth")
                print(f"✅ Saved best model (kappa={best_kappa:.4f})")
            
            # 增强的早停检查（传入额外参数）
            if early_stopping(val_loss, kappa, epoch, model):
                print(f"������ Early stopping triggered after {epoch} epochs")
                break
            
            # 每个epoch都保存训练曲线（确保50轮都有图片）
            plot_training_curves(train_losses, val_losses, kappas, accs, lrs, epoch, model_name, model_figures_dir)
            
            # 每10个epoch保存一个临时完整训练曲线作为备份
            if epoch % 10 == 0 and epoch > 1:
                save_temp_complete_curves(train_losses, val_losses, kappas, accs, lrs, epoch, model_name, model_figures_dir)
                
        except Exception as e:
            print(f"⚠️ Warning: Failed to save figures for epoch {epoch}: {e}")
            # 继续训练，不中断
    
    print(f"Training completed! Best kappa: {best_kappa:.4f}")
    
    # 保存最终完整的训练曲线
    save_final_complete_curves(train_losses, val_losses, kappas, accs, lrs, model_name, model_figures_dir)
    
    return model, train_losses, val_losses, kappas, accs


# ===================== 保存最终完整训练曲线 =====================
def save_final_complete_curves(train_losses, val_losses, kappas, accs, lrs, model_name, save_dir):
    """训练完成后保存最终的完整训练曲线"""
    plt.figure(figsize=(15, 5))
    
    plt.subplot(1, 3, 1)
    plt.plot(range(1, len(train_losses)+1), train_losses, label="Train Loss", 
             alpha=0.8, linewidth=2, marker='o', markersize=3)
    plt.plot(range(1, len(val_losses)+1), val_losses, label="Val Loss", 
             alpha=0.8, linewidth=2, marker='s', markersize=3)
    plt.xlabel("Epoch")
    plt.ylabel("Loss")
    plt.title("Final Complete Loss Curve")
    plt.legend()
    plt.grid(True, alpha=0.3)
    
    plt.subplot(1, 3, 2)
    plt.plot(range(1, len(kappas)+1), kappas, label="Kappa", 
             color='green', alpha=0.8, linewidth=2, marker='o', markersize=3)
    plt.plot(range(1, len(accs)+1), accs, label="Accuracy", 
             color='blue', alpha=0.8, linewidth=2, marker='s', markersize=3)
    plt.xlabel("Epoch")
    plt.ylabel("Score")
    plt.title("Final Complete Metrics")
    plt.legend()
    plt.grid(True, alpha=0.3)
    
    plt.subplot(1, 3, 3)
    plt.plot(range(1, len(lrs)+1), lrs, label="Learning Rate", 
             color='red', alpha=0.8, linewidth=2, marker='o', markersize=3)
    plt.xlabel("Epoch")
    plt.ylabel("Learning Rate")
    plt.title("Learning Rate Schedule")
    plt.yscale('log')
    plt.legend()
    plt.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(os.path.join(save_dir, "final_complete_training_curves.png"), dpi=300, bbox_inches='tight')
    plt.close()
    
    # 保存训练结果摘要
    best_kappa_idx = np.argmax(kappas)
    best_kappa_value = kappas[best_kappa_idx]
    best_acc_idx = np.argmax(accs)
    best_acc_value = accs[best_acc_idx]
    final_val_loss = val_losses[-1]
    final_train_loss = train_losses[-1]
    
    summary_text = f"""
{model_name} Training Summary:
==========================
Best Kappa: {best_kappa_value:.4f} (Epoch {best_kappa_idx + 1})
Best Accuracy: {best_acc_value:.4f} (Epoch {best_acc_idx + 1})
Final Train Loss: {final_train_loss:.4f}
Final Val Loss: {final_val_loss:.4f}
Total Epochs: {len(train_losses)}
Final Learning Rate: {lrs[-1]:.2e}

Training completed successfully!
All figures saved in: {save_dir}
"""
    
    print(summary_text)
    
    # 保存摘要到文件
    with open(os.path.join(save_dir, "training_summary.txt"), "w", encoding="utf-8") as f:
        f.write(summary_text)


# ===================== 绘制训练曲线 =====================
def plot_training_curves(train_losses, val_losses, kappas, accs, lrs, epoch, model_name, save_dir):
    plt.figure(figsize=(15, 5))
    
    plt.subplot(1, 3, 1)
    plt.plot(range(1, len(train_losses)+1), train_losses, label="Train Loss", alpha=0.8)
    plt.plot(range(1, len(val_losses)+1), val_losses, label="Val Loss", alpha=0.8)
    plt.xlabel("Epoch")
    plt.ylabel("Loss")
    plt.title("Loss Curve")
    plt.legend()
    plt.grid(True, alpha=0.3)
    
    plt.subplot(1, 3, 2)
    plt.plot(range(1, len(kappas)+1), kappas, label="Kappa", color='green', alpha=0.8)
    plt.plot(range(1, len(accs)+1), accs, label="Accuracy", color='blue', alpha=0.8)
    plt.xlabel("Epoch")
    plt.ylabel("Score")
    plt.title("Kappa & Accuracy")
    plt.legend()
    plt.grid(True, alpha=0.3)
    
    plt.subplot(1, 3, 3)
    plt.plot(range(1, len(lrs)+1), lrs, label="Learning Rate", color='red', alpha=0.8)
    plt.xlabel("Epoch")
    plt.ylabel("Learning Rate")
    plt.title("Learning Rate Schedule")
    plt.yscale('log')
    plt.legend()
    plt.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(os.path.join(save_dir, f"epoch_{epoch:02d}_training_curves.png"), dpi=150, bbox_inches='tight')
    plt.close()
    
    # 额外保存当前epoch的单独监控图
    plt.figure(figsize=(10, 4))
    
    plt.subplot(1, 2, 1)
    plt.plot(range(1, len(train_losses)+1), train_losses, label="Train Loss", marker='o')
    plt.plot(range(1, len(val_losses)+1), val_losses, label="Val Loss", marker='s')
    plt.xlabel("Epoch")
    plt.ylabel("Loss")
    plt.title(f"Loss Curve (Epoch {epoch})")
    plt.legend()
    plt.grid(True, alpha=0.3)
    
    plt.subplot(1, 2, 2)
    plt.plot(range(1, len(kappas)+1), kappas, label="Kappa", color='green', marker='o')
    plt.plot(range(1, len(accs)+1), accs, label="Accuracy", color='blue', marker='s')
    plt.xlabel("Epoch")
    plt.ylabel("Score")
    plt.title(f"Kappa & Accuracy (Epoch {epoch})")
    plt.legend()
    plt.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(os.path.join(save_dir, f"epoch_{epoch:02d}_metrics.png"), dpi=150, bbox_inches='tight')
    plt.close()


# ===================== 保存临时完整训练曲线 =====================
def save_temp_complete_curves(train_losses, val_losses, kappas, accs, lrs, epoch, model_name, save_dir):
    """每10个epoch保存一次完整的训练曲线"""
    plt.figure(figsize=(15, 5))
    
    plt.subplot(1, 3, 1)
    plt.plot(range(1, len(train_losses)+1), train_losses, label="Train Loss", alpha=0.8, linewidth=2)
    plt.plot(range(1, len(val_losses)+1), val_losses, label="Val Loss", alpha=0.8, linewidth=2)
    plt.xlabel("Epoch")
    plt.ylabel("Loss")
    plt.title(f"Complete Loss Curve (Epoch {epoch})")
    plt.legend()
    plt.grid(True, alpha=0.3)
    
    plt.subplot(1, 3, 2)
    plt.plot(range(1, len(kappas)+1), kappas, label="Kappa", color='green', alpha=0.8, linewidth=2)
    plt.plot(range(1, len(accs)+1), accs, label="Accuracy", color='blue', alpha=0.8, linewidth=2)
    plt.xlabel("Epoch")
    plt.ylabel("Score")
    plt.title(f"Complete Metrics (Epoch {epoch})")
    plt.legend()
    plt.grid(True, alpha=0.3)
    
    plt.subplot(1, 3, 3)
    plt.plot(range(1, len(lrs)+1), lrs, label="Learning Rate", color='red', alpha=0.8, linewidth=2)
    plt.xlabel("Epoch")
    plt.ylabel("Learning Rate")
    plt.title(f"Learning Rate Schedule (Epoch {epoch})")
    plt.yscale('log')
    plt.legend()
    plt.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(os.path.join(save_dir, f"complete_curves_epoch_{epoch:02d}.png"), dpi=150, bbox_inches='tight')
    plt.close()


# ===================== 模型创建函数 =====================
def create_model(model_name, pretrained_path=None, num_classes=5):
    model = timm.create_model(model_name, pretrained=False, num_classes=num_classes)
    
    if pretrained_path and os.path.exists(pretrained_path):
        print(f"Loading pretrained weights from {pretrained_path}")
        try:
            state_dict = torch.load(pretrained_path, map_location='cpu', weights_only=False)
            
            # 处理不同模型的分类头
            if 'fc.weight' in state_dict:
                print("Removing original fc layer (1000 classes)")
                state_dict.pop('fc.weight')
                state_dict.pop('fc.bias')
            elif 'classifier.weight' in state_dict:
                print("Removing original classifier layer (1000 classes)")
                state_dict.pop('classifier.weight')
                state_dict.pop('classifier.bias')
            elif 'head.weight' in state_dict:
                print("Removing original head layer (1000 classes)")
                state_dict.pop('head.weight')
                state_dict.pop('head.bias')
            
            missing_keys, unexpected_keys = model.load_state_dict(state_dict, strict=False)
            print(f"Backbone loaded successfully. Missing: {len(missing_keys)} keys")
            
        except Exception as e:
            print(f"Failed to load pretrained weights: {e}")
    
    return model


# ===================== 入口函数 =====================
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=str, required=True,
                       choices=["resnet50", "resnet152", "densenet121", "efficientnet_b8", 
                               "efficientnet_b3", "efficientnet_b5", "vit_base_patch16_224"])
    parser.add_argument("--pretrained_path", type=str, default=None,
                       help="预训练权重路径")
    args = parser.parse_args()
    
    main(args.model, args.pretrained_path)