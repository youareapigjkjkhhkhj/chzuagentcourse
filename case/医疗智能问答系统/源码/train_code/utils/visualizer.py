import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd
import os

def plot_training_curves(log_dir="logs", save_path="figures/training_curves.png"):
    # 简化版，自己有wandb更好
    plt.figure(figsize=(12,5))
    # 这里省略实际读取代码，实际项目用wandb拉历史
    plt.savefig(save_path)

def plot_all_confusion_matrices(results_df, save_path="figures/cm_all.png"):
    models = results_df['model'].unique()
    fig, axes = plt.subplots(2, 3, figsize=(18,12))
    axes = axes.flatten()
    for idx, model in enumerate(models):
        cm = eval(results_df[results_df['model']==model]['confusion_matrix'].item())
        sns.heatmap(cm, annot=True, fmt='d', cmap='Blues', ax=axes[idx])
        axes[idx].set_title(f'{model}')
    plt.tight_layout()
    plt.savefig(save_path, dpi=300)
    plt.close()