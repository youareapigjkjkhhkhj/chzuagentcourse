#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI模型管理器
"""

import os
import time
import torch
import torch.nn as nn
import numpy as np
from typing import Dict, List, Any, Tuple
import timm
from concurrent.futures import ThreadPoolExecutor, as_completed

class ModelManager:
    """AI模型管理器类"""
    
    def __init__(self):
        self.models = {}
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model_weights = {
            'efficientnet_b3': 0.25,
            'resnet50': 0.20,
            'densenet121': 0.20,
            'efficientnet_b5': 0.15,
            'resnet152': 0.10,
            'efficientnet_b8': 0.10
        }
        
        # 获取当前文件所在目录，然后构建绝对路径
        current_dir = os.path.dirname(os.path.abspath(__file__))  # services目录
        project_root = os.path.dirname(current_dir)  # backend目录
        models_dir = os.path.join(project_root, 'train_model')  # backend/train_model 目录
        
        self.model_paths = {
            'efficientnet_b3': os.path.join(models_dir, 'efficientnet_b3', 'best_efficientnet_b3.pth'),
            'resnet50': os.path.join(models_dir, 'resnet50', 'best_resnet50.pth'),
            'densenet121': os.path.join(models_dir, 'densenet121', 'best_densenet121.pth'),
            'efficientnet_b5': os.path.join(models_dir, 'efficientnet_b5', 'best_efficientnet_b5.pth'),
            'resnet152': os.path.join(models_dir, 'resnet152', 'best_resnet152.pth'),
            'efficientnet_b8': os.path.join(models_dir, 'efficientnet_b8', 'best_efficientnet_b8.pth')
        }
        
        self.load_models()
    
    def load_models(self):
        """加载所有可用的训练好的模型"""
        print(f"=== 开始加载AI模型 ===")
        print(f"设备: {self.device}")
        print(f"模型路径配置: {self.model_paths}")
        
        loaded_count = 0
        
        for model_name, model_path in self.model_paths.items():
            print(f"\n--- 尝试加载模型: {model_name} ---")
            print(f"模型路径: {model_path}")
            print(f"文件是否存在: {os.path.exists(model_path)}")
            
            if os.path.exists(model_path):
                try:
                    print(f"开始创建模型实例...")
                    model = self._create_model(model_name, model_path)
                    print(f"模型创建成功: {type(model)}")
                    
                    print(f"将模型添加到models字典...")
                    self.models[model_name] = model
                    print(f"✅ 成功加载模型: {model_name}")
                    loaded_count += 1
                    
                except Exception as e:
                    print(f"❌ 加载模型失败 {model_name}: {str(e)}")
                    import traceback
                    print(f"加载异常详情: {traceback.format_exc()}")
            else:
                print(f"⚠ 模型文件不存在: {model_path}")
        
        print(f"\n=== 模型加载完成 ===")
        print(f"成功加载 {loaded_count} 个模型")
        print(f"可用模型列表: {list(self.models.keys())}")
        print(f"模型总数: {len(self.models)}")
    
    def _create_model(self, model_name: str, model_path: str) -> nn.Module:
        """创建模型实例并加载权重"""
        print(f"--- 创建模型: {model_name} ---")
        print(f"模型路径: {model_path}")
        
        try:
            print(f"使用timm创建模型: {model_name}")
            model = timm.create_model(model_name, pretrained=False, num_classes=5)
            print(f"模型创建成功，结构: {type(model)}")
            
            if os.path.exists(model_path):
                print(f"开始加载模型权重...")
                print(f"权重文件大小: {os.path.getsize(model_path)} 字节")
                
                # 使用weights_only=True提高安全性
                print(f"加载到设备: {self.device}")
                state_dict = torch.load(model_path, map_location=self.device, weights_only=True)
                print(f"权重加载完成，state_dict键数量: {len(state_dict)}")
                print(f"state_dict前几个键: {list(state_dict.keys())[:5]}")
                
                print(f"开始加载到模型...")
                load_result = model.load_state_dict(state_dict)
                print(f"权重加载结果: {load_result}")
                
            else:
                print(f"⚠ 权重文件不存在，跳过权重加载")
            
            print(f"移动模型到设备: {self.device}")
            model = model.to(self.device)
            
            print(f"设置模型为评估模式")
            model.eval()
            
            print(f"✅ 模型 {model_name} 创建完成")
            return model
            
        except Exception as e:
            print(f"❌ 创建模型 {model_name} 失败: {str(e)}")
            import traceback
            print(f"创建异常详情: {traceback.format_exc()}")
            raise
    
    def predict_single_model(self, model_name: str, image_tensor: torch.Tensor) -> Dict[str, Any]:
        """单个模型预测"""
        print(f"=== 开始单个模型预测: {model_name} ===")
        print(f"模型在models字典中: {model_name in self.models}")
        print(f"可用模型列表: {list(self.models.keys())}")
        print(f"图像张量形状: {image_tensor.shape}")
        print(f"图像张量设备: {image_tensor.device}")
        
        if model_name not in self.models:
            error_msg = f"模型 {model_name} 未加载"
            print(f"❌ {error_msg}")
            raise ValueError(error_msg)
        
        model = self.models[model_name]
        print(f"✅ 成功获取模型实例: {type(model)}")
        
        start_time = time.time()
        
        try:
            with torch.no_grad():
                # 确保图像在正确的设备上
                image_tensor = image_tensor.to(self.device)
                print(f"图像张量移动到设备后: {image_tensor.device}")
                
                # 确保图像是4D张量 (batch_size, channels, height, width)
                if image_tensor.dim() == 3:
                    # 3D张量，添加batch维度
                    image_tensor = image_tensor.unsqueeze(0)
                    print(f"从3D张量添加batch维度: {image_tensor.shape}")
                elif image_tensor.dim() == 4:
                    # 已经是4D张量，直接使用
                    print(f"4D张量，无需修改: {image_tensor.shape}")
                else:
                    raise ValueError(f"图像张量维度不正确，应该是3D或4D，实际是 {image_tensor.dim()}D: {image_tensor.shape}")
                
                print(f"开始模型推理...")
                logits = model(image_tensor)
                print(f"推理完成，logits形状: {logits.shape}")
                
                logits_cpu = logits.detach().cpu()
                del logits
                
                probabilities = torch.softmax(logits_cpu, dim=1)
                print(f"概率分布形状: {probabilities.shape}")
                
                predicted_class = torch.argmax(probabilities, dim=1).item()
                confidence = probabilities[0, predicted_class].item()
                
                print(f"预测类别: {predicted_class}")
                print(f"置信度: {confidence:.4f}")
                
                class_probs = probabilities[0].numpy().tolist()
                print(f"各类别概率: {class_probs}")
                
            processing_time = time.time() - start_time
            print(f"✅ 模型预测成功，用时: {processing_time:.4f}秒")
            
            return {
                'model_name': model_name,
                'predicted_class': predicted_class,
                'confidence': confidence,
                'class_probabilities': {
                    '0': class_probs[0],  # 无糖尿病视网膜病变
                    '1': class_probs[1],  # 轻度非增殖性
                    '2': class_probs[2],  # 中度非增殖性
                    '3': class_probs[3],  # 重度非增殖性
                    '4': class_probs[4],  # 增殖性
                },
                'processing_time': processing_time
            }
            
        except Exception as e:
            print(f"❌ 模型 {model_name} 预测过程发生异常: {str(e)}")
            print(f"异常类型: {type(e)}")
            import traceback
            print(f"异常详情: {traceback.format_exc()}")
            raise ValueError(f"模型 {model_name} 预测失败: {str(e)}")
    
    def ensemble_predict(self, image_tensor: torch.Tensor, model_names: List[str] = None) -> Dict[str, Any]:
        """集成模型预测"""
        if model_names is None:
            model_names = list(self.models.keys())
        
        if not model_names:
            raise ValueError("没有可用的模型进行预测")
        
        start_time = time.time()
        
        # 并行预测
        predictions = {}
        with ThreadPoolExecutor(max_workers=min(len(model_names), 4)) as executor:
            future_to_model = {
                executor.submit(self.predict_single_model, model_name, image_tensor): model_name 
                for model_name in model_names if model_name in self.models
            }
            
            for future in as_completed(future_to_model):
                model_name = future_to_model[future]
                try:
                    pred = future.result()
                    predictions[model_name] = pred
                except Exception as e:
                    print(f"模型 {model_name} 预测失败: {str(e)}")
        
        if not predictions:
            raise ValueError("所有模型预测都失败了")
        
        # 加权集成
        ensemble_probs = np.zeros(5)
        total_weight = 0.0
        
        for model_name, pred in predictions.items():
            weight = self.model_weights.get(model_name, 0.1)
            for i in range(5):
                ensemble_probs[i] += pred['class_probabilities'][str(i)] * weight
            total_weight += weight
        
        # 归一化
        if total_weight > 0:
            ensemble_probs /= total_weight
        
        # 最终预测
        final_prediction = int(np.argmax(ensemble_probs))
        final_confidence = float(ensemble_probs[final_prediction])
        
        total_processing_time = time.time() - start_time
        
        return {
            'individual_predictions': predictions,
            'ensemble_prediction': {
                'predicted_class': final_prediction,
                'confidence': final_confidence,
                'class_probabilities': {
                    '0': float(ensemble_probs[0]),
                    '1': float(ensemble_probs[1]),
                    '2': float(ensemble_probs[2]),
                    '3': float(ensemble_probs[3]),
                    '4': float(ensemble_probs[4])
                }
            },
            'model_count': len(predictions),
            'total_processing_time': total_processing_time,
            'models_used': list(predictions.keys())
        }
    
    def get_available_models(self) -> List[str]:
        """获取可用的模型列表"""
        return list(self.models.keys())
    
    def get_model_info(self) -> Dict[str, Any]:
        """获取模型信息"""
        return {
            'device': str(self.device),
            'available_models': list(self.models.keys()),
            'model_weights': self.model_weights,
            'total_models': len(self.models)
        }
