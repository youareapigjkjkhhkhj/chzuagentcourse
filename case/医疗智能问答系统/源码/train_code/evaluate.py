# evaluate.py
import torch, os, pandas as pd, numpy as np, matplotlib.pyplot as plt, seaborn as sns
from sklearn.metrics import cohen_kappa_score, confusion_matrix, accuracy_score, classification_report
from tqdm import tqdm
import timm
from torch.utils.data import DataLoader
import albumentations as A
from albumentations.pytorch import ToTensorV2
from confi1 import CFG

# 同 train.py 中的 Dataset 和 transform
# ...（直接复制上面的 APTOSDataset 和 val_transform）
from train_efficb3 import APTOSDataset
@torch.no_grad()
def get_predictions(model_name, ckpt_path):
    model = timm.create_model(model_name, pretrained=False, num_classes=5)
    state_dict = torch.load(ckpt_path, map_location='cuda')
    model.load_state_dict(state_dict)
    model.cuda().eval()

    ds = APTOSDataset('dataset/test_internal.csv', CFG.train_img_dir,
                       transform=A.Compose([
                           A.Resize(256,256),
                           A.CenterCrop(224,224),
                           A.CLAHE(clip_limit=2.0),
                           A.Normalize(mean=[0.485,0.456,0.406],std=[0.229,0.224,0.225]),
                           ToTensorV2()
                       ]))
    dl = DataLoader(ds, batch_size=64, num_workers=8)
    preds, trues = [], []
    for x, y in tqdm(dl, desc=model_name):
        x = x.cuda()
        logits = model(x)

        # TTA
        for _ in range(9):
            x_np = x.permute(0,2,3,1).cpu().numpy()
            aug_imgs = np.array([A.HorizontalFlip(p=1.0)(image=img)['image'] for img in x_np])
            aug_imgs = torch.from_numpy(aug_imgs).permute(0,3,1,2).cuda()
            logits += model(aug_imgs)
        logits /= 10

        pred = logits.argmax(1).cpu().numpy()
        preds.extend(pred)
        trues.extend(y.numpy())
    return np.array(preds), np.array(trues)


results = []
for ckpt_file in os.listdir('models/'):
    if not ckpt_file.endswith('.ckpt'): continue
    model_name = ckpt_file.split('-')[0]  # 粗暴取名，你实际可改成保存时带model名更准
    # 下面手动映射或改成在ckpt里保存hparams
    name_map = {...} # 你自己填
    preds, labels = get_predictions('efficientnet_b3', f'models/{ckpt_file}')  # 示例
    kappa = cohen_kappa_score(labels, preds, weights='quadratic')
    acc = accuracy_score(labels, preds)
    cm = confusion_matrix(labels, preds)
    results.append({'model':model_name, 'QWK':kappa, 'Acc':acc, 'cm':cm})

df = pd.DataFrame(results)
df.to_excel('figures/final_performance.xlsx', index=False)
print(df)