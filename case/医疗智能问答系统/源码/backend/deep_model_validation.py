#!/usr/bin/env python3
import sys
import os
sys.path.append('.')
import torch
import numpy as np
from PIL import Image
import matplotlib.pyplot as plt

from services.model_manager import ModelManager
from services.image_processor import ImageProcessor

def test_model_reality():
    """深度验证模型是否真的在学习特征"""
    print("=== 深度模型真实性验证测试 ===\n")
    
    # 创建模型管理器和图像处理器
    model_manager = ModelManager()
    image_processor = ImageProcessor()
    
    print(f"可用模型: {model_manager.get_available_models()}")
    
    # 获取所有可用的测试图像
    image_dir = 'uploads/images/'
    if not os.path.exists(image_dir):
        print(f"图像目录不存在: {image_dir}")
        return
    
    image_files = [f for f in os.listdir(image_dir) if f.endswith('.png')]
    print(f"找到 {len(image_files)} 个测试图像: {image_files}")
    
    if len(image_files) < 2:
        print("需要至少2个不同的图像来测试模型变化性")
        return
    
    # 测试不同的模型
    test_models = ['efficientnet_b3', 'resnet50']
    results = {}
    
    for model_name in test_models:
        if model_name not in model_manager.get_available_models():
            print(f"⚠ 模型 {model_name} 不可用")
            continue
            
        print(f"\n{'='*50}")
        print(f"测试模型: {model_name}")
        print(f"{'='*50}")
        
        model_results = []
        
        for i, image_file in enumerate(image_files):
            image_path = os.path.join(image_dir, image_file)
            print(f"\n--- 图像 {i+1}: {image_file} ---")
            
            try:
                # 处理图像
                result = image_processor.preprocess_uploaded_image(image_path)
                processed_image = result['processed_image']
                print(f"原始图像: {image_file}")
                print(f"处理后形状: {processed_image.shape}")
                print(f"质量等级: {result['quality_level']}")
                
                # 预测
                pred = model_manager.predict_single_model(model_name, processed_image)
                
                print(f"预测结果:")
                print(f"  类别: {pred['predicted_class']}")
                print(f"  置信度: {pred['confidence']:.4f}")
                print(f"  各类别概率: {pred['class_probabilities']}")
                
                # 记录详细结果
                model_results.append({
                    'image': image_file,
                    'prediction': pred['predicted_class'],
                    'confidence': pred['confidence'],
                    'probabilities': pred['class_probabilities'],
                    'quality': result['quality_level']
                })
                
            except Exception as e:
                print(f"❌ 图像 {image_file} 预测失败: {str(e)}")
                continue
        
        results[model_name] = model_results
        
        # 分析模型是否真的在学习
        print(f"\n📊 模型 {model_name} 分析结果:")
        
        if len(model_results) >= 2:
            # 检查预测结果变化
            predictions = [r['prediction'] for r in model_results]
            confidences = [r['confidence'] for r in model_results]
            
            unique_predictions = set(predictions)
            confidence_std = np.std(confidences)
            
            print(f"  预测类别变化: {predictions}")
            print(f"  不同预测数量: {len(unique_predictions)}")
            print(f"  置信度标准差: {confidence_std:.4f}")
            
            if len(unique_predictions) > 1:
                print(f"  ✅ 模型对不同图像产生不同预测 - 可能在学习特征")
            else:
                print(f"  ⚠ 模型对所有图像返回相同预测 - 可能存在问题")
            
            if confidence_std > 0.01:
                print(f"  ✅ 置信度有显著变化 - 可能在学习特征")
            else:
                print(f"  ⚠ 置信度变化很小 - 可能存在问题")
        else:
            print(f"  ⚠ 结果数量不足，无法分析")
    
    # 综合分析
    print(f"\n{'='*60}")
    print("🎯 综合分析结论:")
    print(f"{'='*60}")
    
    for model_name, model_results in results.items():
        if len(model_results) < 2:
            continue
            
        predictions = [r['prediction'] for r in model_results]
        confidences = [r['confidence'] for r in model_results]
        
        unique_preds = set(predictions)
        confidence_variance = np.var(confidences)
        
        print(f"\n模型 {model_name}:")
        print(f"  预测变化性: {'✅ 有变化' if len(unique_preds) > 1 else '❌ 无变化'}")
        print(f"  置信度方差: {confidence_variance:.6f}")
        
        # 进一步分析
        if len(unique_preds) <= 1 and confidence_variance < 0.001:
            print(f"  🔍 诊断: 模型可能存在问题 - 对所有输入返回相同结果")
            print(f"  💡 建议: 检查模型权重是否正确加载")
        elif len(unique_preds) > 1 or confidence_variance >= 0.001:
            print(f"  ✅ 模型行为正常 - 对不同输入产生不同输出")
    
    print(f"\n=== 测试完成 ===")

def test_with_synthetic_data():
    """使用合成数据测试模型响应"""
    print(f"\n{'='*60}")
    print("🧪 合成数据测试")
    print(f"{'='*60}")
    
    model_manager = ModelManager()
    
    # 创建两个不同的随机张量
    # 模拟不同的图像输入
    synthetic_input1 = torch.randn(3, 224, 224)  # 随机噪声图像1
    synthetic_input2 = torch.randn(3, 224, 224)  # 随机噪声图像2
    
    print(f"合成输入1形状: {synthetic_input1.shape}")
    print(f"合成输入2形状: {synthetic_input2.shape}")
    
    test_model = 'efficientnet_b3'
    if test_model not in model_manager.get_available_models():
        print(f"模型 {test_model} 不可用")
        return
    
    try:
        print(f"\n--- 合成输入1测试 ---")
        pred1 = model_manager.predict_single_model(test_model, synthetic_input1)
        print(f"预测类别: {pred1['predicted_class']}")
        print(f"置信度: {pred1['confidence']:.4f}")
        
        print(f"\n--- 合成输入2测试 ---")
        pred2 = model_manager.predict_single_model(test_model, synthetic_input2)
        print(f"预测类别: {pred2['predicted_class']}")
        print(f"置信度: {pred2['confidence']:.4f}")
        
        # 比较结果
        if pred1['predicted_class'] != pred2['predicted_class'] or \
           abs(pred1['confidence'] - pred2['confidence']) > 0.01:
            print(f"\n✅ 模型对不同输入产生不同输出 - 正常工作")
        else:
            print(f"\n⚠ 模型对不同输入产生相同输出 - 可能存在问题")
            
    except Exception as e:
        print(f"❌ 合成数据测试失败: {str(e)}")

if __name__ == "__main__":
    test_model_reality()
    test_with_synthetic_data()