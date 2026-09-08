import re
import matplotlib.pyplot as plt
import os

def parse_log_file(log_path):
    """解析训练日志文件，提取训练数据"""
    epochs = []
    train_losses = []
    val_losses = []
    kappas = []
    accs = []
    
    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            # 匹配格式: [Epoch X] Train Loss: X.XXXX | Val Loss: X.XXXX | Kappa: X.XXXX | Acc: X.XXXX
            match = re.search(r'\[Epoch\s+(\d+)\]\s+Train\s+Loss:\s+([\d.]+)\s+\|\s+Val\s+Loss:\s+([\d.]+)\s+\|\s+Kappa:\s+([\d.]+)\s+\|\s+Acc:\s+([\d.]+)', line)
            if match:
                epoch = int(match.group(1))
                train_loss = float(match.group(2))
                val_loss = float(match.group(3))
                kappa = float(match.group(4))
                acc = float(match.group(5))
                
                epochs.append(epoch)
                train_losses.append(train_loss)
                val_losses.append(val_loss)
                kappas.append(kappa)
                accs.append(acc)
    
    return epochs, train_losses, val_losses, kappas, accs

def plot_training_curves(model_name, log_path, output_dir):
    """生成训练曲线图"""
    epochs, train_losses, val_losses, kappas, accs = parse_log_file(log_path)
    
    if not epochs:
        print(f"No data found in {log_path}")
        return
    
    # 创建图形
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    
    # 左图：Loss曲线
    ax1 = axes[0]
    ax1.plot(epochs, train_losses, 'b-', label='Train Loss', linewidth=1.5)
    ax1.plot(epochs, val_losses, 'orange', label='Val Loss', linewidth=1.5)
    ax1.set_xlabel('Epoch', fontsize=11)
    ax1.set_ylabel('Loss', fontsize=11)
    ax1.set_title('Loss Curve', fontsize=12)
    ax1.legend(loc='upper right')
    ax1.grid(True, alpha=0.3)
    
    # 右图：Kappa和Accuracy曲线
    ax2 = axes[1]
    ax2.plot(epochs, kappas, 'b-', label='Kappa', linewidth=1.5)
    ax2.plot(epochs, accs, 'orange', label='Accuracy', linewidth=1.5)
    ax2.set_xlabel('Epoch', fontsize=11)
    ax2.set_ylabel('Score', fontsize=11)
    ax2.set_title('Kappa & Accuracy', fontsize=12)
    ax2.legend(loc='lower right')
    ax2.grid(True, alpha=0.3)
    
    plt.tight_layout()
    
    # 保存图片
    output_path = os.path.join(output_dir, 'final_train_val_curve.png')
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"Saved: {output_path}")
    
    # 打印最佳结果
    best_kappa_idx = kappas.index(max(kappas))
    print(f"{model_name} - Best Kappa: {kappas[best_kappa_idx]:.4f} at Epoch {epochs[best_kappa_idx]}")
    print(f"{model_name} - Final Train Loss: {train_losses[-1]:.4f}, Val Loss: {val_losses[-1]:.4f}")
    
    plt.close()

# 定义日志文件和输出目录
logs = [
    ('ResNet-50', 'ecoh50.txt', 'figures/resnet50'),
    ('ResNet-152', 'echo152.txt', 'figures/resnet152'),
    ('EfficientNet-B3', 'echoeffb3.txt', 'figures/efficientnet_b3'),
    ('EfficientNet-B5', 'echob5.txt', 'figures/efficientnet_b5'),
]

# 生成每个模型的训练曲线
for model_name, log_file, output_dir in logs:
    log_path = os.path.join(os.path.dirname(__file__), log_file)
    output_path = os.path.join(os.path.dirname(__file__), output_dir)
    
    # 确保输出目录存在
    os.makedirs(output_path, exist_ok=True)
    
    if os.path.exists(log_path):
        print(f"\nProcessing {model_name}...")
        plot_training_curves(model_name, log_path, output_path)
    else:
        print(f"Log file not found: {log_path}")

print("\nAll training curves generated!")
