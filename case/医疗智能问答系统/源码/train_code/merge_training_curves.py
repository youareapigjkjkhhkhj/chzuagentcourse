import matplotlib.pyplot as plt
import matplotlib.image as mpimg
import os

# 定义六张图片的路径
model_images = [
    ('EfficientNet-B8', 'figures/efficientnet_b8/final_train_val_curve.png'),
    ('EfficientNet-B5', 'figures/efficientnet_b5/final_train_val_curve.png'),
    ('EfficientNet-B3', 'figures/efficientnet_b3/final_train_val_curve.png'),
    ('ResNet-152', 'figures/resnet152/final_train_val_curve.png'),
    ('ResNet-50', 'figures/resnet50/final_train_val_curve.png'),
    ('DenseNet-121', 'figures/densenet121/final_train_val_curve.png'),
]

# 创建大图 (3行2列)
fig, axes = plt.subplots(3, 2, figsize=(16, 18))
fig.suptitle('Training Curves of Six Deep Learning Models', fontsize=16, fontweight='bold', y=0.98)

base_dir = os.path.dirname(__file__)

for idx, (model_name, img_path) in enumerate(model_images):
    row = idx // 2
    col = idx % 2
    ax = axes[row, col]
    
    full_path = os.path.join(base_dir, img_path)
    
    if os.path.exists(full_path):
        img = mpimg.imread(full_path)
        ax.imshow(img)
        ax.set_title(f'({chr(97+idx)}) {model_name}', fontsize=12, fontweight='bold', pad=10)
        ax.axis('off')
    else:
        ax.text(0.5, 0.5, f'Image not found:\n{img_path}', 
                ha='center', va='center', fontsize=10)
        ax.set_title(f'({chr(97+idx)}) {model_name}', fontsize=12, fontweight='bold')
        ax.axis('off')

plt.tight_layout(rect=[0, 0, 1, 0.96])

# 保存合并后的图片
output_path = os.path.join(base_dir, 'figures', 'all_models_training_curves.png')
os.makedirs(os.path.dirname(output_path), exist_ok=True)
plt.savefig(output_path, dpi=200, bbox_inches='tight', facecolor='white')
print(f"Saved merged image: {output_path}")

# 同时保存一个适合论文使用的版本 (更高DPI)
output_path_high = os.path.join(base_dir, 'figures', 'all_models_training_curves_hd.png')
plt.savefig(output_path_high, dpi=300, bbox_inches='tight', facecolor='white')
print(f"Saved high-res image: {output_path_high}")

plt.close()

# 创建一个横向排列的版本 (2行3列，更适合宽屏展示)
fig2, axes2 = plt.subplots(2, 3, figsize=(20, 12))
fig2.suptitle('Training Curves of Six Deep Learning Models', fontsize=16, fontweight='bold', y=0.98)

for idx, (model_name, img_path) in enumerate(model_images):
    row = idx // 3
    col = idx % 3
    ax = axes2[row, col]
    
    full_path = os.path.join(base_dir, img_path)
    
    if os.path.exists(full_path):
        img = mpimg.imread(full_path)
        ax.imshow(img)
        ax.set_title(f'({chr(97+idx)}) {model_name}', fontsize=12, fontweight='bold', pad=10)
        ax.axis('off')
    else:
        ax.text(0.5, 0.5, f'Image not found:\n{img_path}', 
                ha='center', va='center', fontsize=10)
        ax.set_title(f'({chr(97+idx)}) {model_name}', fontsize=12, fontweight='bold')
        ax.axis('off')

plt.tight_layout(rect=[0, 0, 1, 0.96])

# 保存横向版本
output_path2 = os.path.join(base_dir, 'figures', 'all_models_training_curves_wide.png')
plt.savefig(output_path2, dpi=200, bbox_inches='tight', facecolor='white')
print(f"Saved wide layout: {output_path2}")

plt.close()

print("\nAll merged images generated successfully!")
print("\nGenerated files:")
print(f"1. {output_path} - 3x2布局，适合纵向排版")
print(f"2. {output_path_high} - 高清版本(300DPI)")
print(f"3. {output_path2} - 2x3横向布局，适合横向排版")
