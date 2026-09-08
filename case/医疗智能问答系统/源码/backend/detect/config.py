# config.py
class CFG:
    seed = 42
    num_classes = 5
    img_size = 224
    mean = (0.485, 0.456, 0.406)
    std  = (0.229, 0.224, 0.225)
    batch_size = 32
    epochs = 50
    lr = 1e-4
    weight_decay = 0.05
    patience = 15

    # APTOS 2019 各类别大致数量（用于加权损失）
    class_freq = [1805, 370, 999, 193, 295]
    data_root = "../datasets"
    train_img_dir = "../datasets/train_images"
