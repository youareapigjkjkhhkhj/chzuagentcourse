# test_tta.py
import os
import cv2
import torch    
import timm
import numpy as np
import pandas as pd
from tqdm import tqdm
from sklearn.metrics import cohen_kappa_score, accuracy_score
from albumentations import Compose, Resize, CenterCrop, CLAHE, Normalize, HorizontalFlip
from albumentations.pytorch import ToTensorV2
from confi1 import CFG


# ======================= Dataset =======================
class TestDataset:
    def __init__(self, csv_path):
        import pandas as pd
        self.df = pd.read_csv(csv_path)

        self.transform = Compose([
            Resize(256, 256),
            CenterCrop(CFG.img_size, CFG.img_size),
            CLAHE(clip_limit=2.0),
            Normalize(mean=[0.485, 0.456, 0.406],
                      std=[0.229, 0.224, 0.225]),
            ToTensorV2()
        ])

    def __len__(self):
        return len(self.df)

    def __getitem__(self, i):
        row = self.df.iloc[i]
        img_path = f"data/train_images/{row.id_code}"
        img = cv2.imread(img_path)
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

        img = self.transform(image=img)["image"]
        return img, row.diagnosis


# ======================= Load Model =======================
def load_model(model_name, pth_path, device):
    model = timm.create_model(model_name, pretrained=False, num_classes=5)
    state = torch.load(pth_path, map_location=device)
    model.load_state_dict(state)
    model.to(device)
    model.eval()
    return model


# ======================= TTA 推理 =======================
@torch.no_grad()
def tta_predict(model, img, device):
    img = img.unsqueeze(0).to(device)
    logits = model(img)

    # TTA 多次水平翻转
    for _ in range(CFG.tta_steps - 1):
        tta_img = HorizontalFlip(p=1)(image=img[0].cpu().numpy())["image"]
        tta_img = torch.tensor(tta_img).unsqueeze(0).float().to(device)
        logits += model(tta_img)

    logits = logits / CFG.tta_steps
    pred = logits.argmax(1).item()
    prob = torch.softmax(logits, dim=1)[0].cpu().numpy()
    return pred, prob


# ======================= MAIN =======================
if __name__ == "__main__":
    device = "cuda" if torch.cuda.is_available() else "cpu"

    # 所有模型的 best.pth
    weight_files = [f for f in os.listdir("models") if f.endswith(".pth")]

    results = []

    print("\n========== 开始 TTA 测试 ==========\n")

    for wf in weight_files:
        model_name = wf.split("best_")[-1].replace(".pth", "")
        print(f"\n>>> 测试 {model_name} ...")

        # 载入模型
        model = load_model(model_name, f"models/{wf}", device)

        # 载入数据集
        ds = TestDataset("dataset/test.csv")

        preds, labels = [], []

        for img, label in tqdm(ds, desc=model_name):
            pred, _ = tta_predict(model, img, device)
            preds.append(pred)
            labels.append(label)

        # 指标
        qwk = cohen_kappa_score(labels, preds, weights="quadratic")
        acc = accuracy_score(labels, preds)

        results.append({
            "model": model_name,
            "QWK": round(qwk, 4),
            "Acc": round(acc, 4),
        })

    # 保存到 Excel
    df = pd.DataFrame(results)
    os.makedirs("figures", exist_ok=True)
    df.to_excel("figures/final_results.xlsx", index=False)

    print("\n========== 最终结果 ==========\n")
    print(df)
    print("\n结果已保存到 figures/final_results.xlsx\n")
