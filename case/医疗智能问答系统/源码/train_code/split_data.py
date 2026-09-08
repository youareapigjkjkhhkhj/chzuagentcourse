import pandas as pd
from sklearn.model_selection import StratifiedShuffleSplit
import os

# 读取原始数据
df = pd.read_csv('data/train.csv')
df['id_code'] = df['id_code'].astype(str) + '.png'

print(f"总数据量: {len(df)}")
print("各类别分布:")
print(df['diagnosis'].value_counts().sort_index())

# 80% train, 20% temp (然后temp再分成val和test)
sss = StratifiedShuffleSplit(n_splits=1, test_size=0.2, random_state=42)
train_idx, temp_idx = next(sss.split(df, df['diagnosis']))
train_df = df.iloc[train_idx]

# 将temp数据分成val和test
temp_df = df.iloc[temp_idx]
sss2 = StratifiedShuffleSplit(n_splits=1, test_size=0.5, random_state=42)
val_idx, test_idx = next(sss2.split(temp_df, temp_df['diagnosis']))
val_df = temp_df.iloc[val_idx]
test_df = temp_df.iloc[test_idx]

# 创建dataset目录
os.makedirs('dataset', exist_ok=True)

# 保存分割后的数据
train_df.to_csv('dataset/train.csv', index=False)
val_df.to_csv('dataset/val.csv', index=False)
test_df.to_csv('dataset/test_internal.csv', index=False)

print(f"\n数据分割完成:")
print(f"训练集: {len(train_df)} ({len(train_df)/len(df)*100:.1f}%)")
print(f"验证集: {len(val_df)} ({len(val_df)/len(df)*100:.1f}%)")
print(f"内部测试集: {len(test_df)} ({len(test_df)/len(df)*100:.1f}%)")

print("\n各类别分布:")
print("训练集:", train_df['diagnosis'].value_counts().sort_index().tolist())
print("验证集:", val_df['diagnosis'].value_counts().sort_index().tolist())
print("测试集:", test_df['diagnosis'].value_counts().sort_index().tolist())