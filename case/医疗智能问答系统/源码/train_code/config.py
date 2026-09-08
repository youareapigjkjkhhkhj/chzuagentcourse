# config.py
class CFG:
    seed = 42
    num_classes = 5
    img_size = 224
    mean = (0.485, 0.456, 0.406)
    std  = (0.229, 0.224, 0.225)
    
    # 增大batch_size，因为少数类需要更多样本参与计算
    batch_size = 32  # 从16增大到32
    
    # 增加epoch数，但配合早停使用
    epochs = 50
    lr = 1e-4  # 降低学习率，减少过拟合风险
    weight_decay = 0.1  # 增加权重衰减，加强正则化
    
    # 早停patience调小
    patience = 10  # 原来是15
    
    # Dropout和随机失活 - 增强dropout减少过拟合
    dropout_rate = 0.7
    
    # 梯度裁剪
    grad_clip = 1.0
    
    # APTOS 2019 各类别大致数量（用于加权损失）
    class_freq = [1805, 370, 999, 193, 295]
    data_root = "data"
    train_img_dir = "data/train_images"