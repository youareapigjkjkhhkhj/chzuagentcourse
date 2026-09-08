#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
图像处理服务
"""

import os
import io
import cv2
import numpy as np
import hashlib
from PIL import Image
from typing import Dict, Any, Tuple

# 禁用albumentations版本检查，避免网络超时
os.environ['ALBUMENTATIONS_NO_NETWORK'] = '1'
os.environ['ALBUMENTATIONS_DISABLE_VERSION_CHECK'] = '1'

import albumentations as A
from albumentations.pytorch import ToTensorV2

class ImageProcessor:
    """图像处理器类"""
    
    def __init__(self):
        # 图像预处理变换
        self.transform = A.Compose([
            A.Resize(224, 224),
            A.Normalize(mean=(0.485, 0.456, 0.406), std=(0.229, 0.224, 0.225)),
            ToTensorV2(),
        ])
    
    def preprocess_uploaded_image(self, image_file) -> Dict[str, Any]:
        """预处理上传的图像"""
        print(f"=== 图像处理开始 ===")
        print(f"输入参数类型: {type(image_file)}")
        print(f"输入参数值: {image_file}")
        
        # 检查输入类型，支持文件对象或文件路径
        if isinstance(image_file, str):
            # 文件路径
            image_path = image_file
            print(f"文件路径处理: {image_path}")
            print(f"文件路径类型: {type(image_path)}")
            print(f"文件路径长度: {len(image_path)}")
            print(f"文件路径编码: {image_path.encode('utf-8')[:50]}...")
            
            # 检查文件是否存在
            print(f"检查文件存在性...")
            file_exists = os.path.exists(image_path)
            print(f"文件是否存在: {file_exists}")
            
            if not file_exists:
                # 尝试绝对路径
                abs_path = os.path.abspath(image_path)
                print(f"尝试绝对路径: {abs_path}")
                abs_exists = os.path.exists(abs_path)
                print(f"绝对路径是否存在: {abs_exists}")
                
                if abs_exists:
                    image_path = abs_path
                    print(f"使用绝对路径: {image_path}")
                else:
                    raise ValueError(f"文件不存在: {image_path}")
            
            # 检查文件大小
            print(f"检查文件大小...")
            try:
                file_size = os.path.getsize(image_path)
                print(f"文件大小: {file_size} 字节")
            except Exception as e:
                print(f"获取文件大小失败: {e}")
                raise ValueError(f"无法获取文件大小: {image_path}")
            
            # 读取原始图像数据进行哈希计算
            print(f"读取图像数据...")
            try:
                with open(image_path, 'rb') as f:
                    image_data = f.read()
                    image_array = np.frombuffer(image_data, np.uint8)
                
                print(f"图像数据长度: {len(image_data)} 字节")
                print(f"图像数据前20字节: {image_data[:20]}")
                print(f"图像数组形状: {image_array.shape}")
            except Exception as e:
                print(f"读取图像数据失败: {e}")
                raise ValueError(f"无法读取图像数据: {image_path}")
            
            # 尝试用OpenCV读取
            print(f"尝试OpenCV读取...")
            try:
                image = cv2.imread(image_path)
                print(f"OpenCV读取结果: {image is not None}")
                if image is not None:
                    print(f"OpenCV图像形状: {image.shape}")
            except Exception as e:
                print(f"OpenCV读取异常: {e}")
                image = None
            
            if image is None:
                # 尝试使用PIL读取
                print(f"尝试PIL读取...")
                try:
                    from PIL import Image as PILImage
                    pil_image = PILImage.open(image_path)
                    print(f"PIL读取成功: {pil_image.size}, {pil_image.mode}")
                    
                    # 转换为numpy数组
                    image = np.array(pil_image.convert('RGB'))
                    print(f"转换后的图像形状: {image.shape}")
                    
                except Exception as e:
                    print(f"PIL读取失败: {e}")
                    raise ValueError(f"无法读取图像文件: {image_path}")
            else:
                # 转换为RGB
                print(f"转换OpenCV图像到RGB...")
                image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                print(f"OpenCV读取成功，图像形状: {image.shape}")
            
            # 计算图像哈希值
            print(f"计算图像哈希...")
            image_hash = hashlib.sha256(image_data).hexdigest()
            print(f"图像哈希值: {image_hash[:16]}...")
            
        else:
            # 文件对象
            print(f"处理文件对象...")
            image_path = None
            print(f"文件对象类型: {type(image_file)}")
            print(f"文件对象属性: {dir(image_file)}")
            
            try:
                # 保存文件对象的当前位置
                original_pos = image_file.tell()
                print(f"文件原始位置: {original_pos}")
                
                # 重置到开始位置
                image_file.seek(0)
                print(f"重置文件位置到: {image_file.tell()}")
                
                # 读取数据
                image_data = image_file.read()
                print(f"读取文件数据长度: {len(image_data)} 字节")
                image_array = np.frombuffer(image_data, np.uint8)
                print(f"图像数组形状: {image_array.shape}")
                
                # 计算图像哈希值
                image_hash = hashlib.sha256(image_data).hexdigest()
                print(f"图像哈希值: {image_hash[:16]}...")
                
                # 尝试用OpenCV解码
                print(f"尝试OpenCV解码...")
                image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
                print(f"OpenCV解码结果: {image is not None}")
                
                if image is not None:
                    print(f"OpenCV解码图像形状: {image.shape}")
                    image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                    print(f"转换到RGB成功，形状: {image.shape}")
                else:
                    # 尝试用PIL解码
                    print(f"尝试PIL解码...")
                    from PIL import Image as PILImage
                    pil_image = PILImage.open(io.BytesIO(image_data))
                    print(f"PIL解码成功: {pil_image.size}, {pil_image.mode}")
                    image = np.array(pil_image.convert('RGB'))
                    print(f"PIL转换图像形状: {image.shape}")
                
                # 恢复文件位置
                image_file.seek(original_pos)
                print(f"恢复文件位置到: {image_file.tell()}")
                
            except Exception as e:
                print(f"文件对象处理失败: {e}")
                raise ValueError(f"无法处理文件对象: {e}")
        
        if image is None:
            print(f"图像解码失败，所有方法都返回None")
            raise ValueError("无法解码图像数据")
        
        print(f"开始质量检查...")
        # 质量检查
        quality_score = self.assess_image_quality(image)
        quality_level = self.get_quality_level(quality_score)
        print(f"质量检查完成: 分数={quality_score:.3f}, 等级={quality_level}")
        
        print(f"开始图像预处理...")
        # 预处理
        processed = self.transform(image=image)['image']
        print(f"预处理完成: 处理后图像形状={processed.shape}")
        
        result = {
            'processed_image': processed,
            'original_image': image,
            'quality_score': quality_score,
            'quality_level': quality_level,
            'image_hash': image_hash,
            'image_shape': image.shape
        }
        
        print(f"=== 图像处理完成 ===")
        print(f"最终结果: {list(result.keys())}")
        print(f"图像哈希: {image_hash[:16]}...")
        print(f"图像形状: {image.shape}")
        print(f"质量等级: {quality_level}")
        
        return result
    
    def assess_image_quality(self, image: np.ndarray) -> float:
        """评估图像质量"""
        # 清晰度检查 (拉普拉斯方差)
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        sharpness = cv2.Laplacian(gray, cv2.CV_64F).var()
        
        # 亮度检查
        brightness = np.mean(gray)
        
        # 对比度检查
        contrast = gray.std()
        
        # 综合评分 (0-1)
        quality_score = (
            min(sharpness / 100, 1.0) * 0.4 +  # 清晰度权重40%
            (1 - abs(brightness - 128) / 128) * 0.3 +  # 亮度权重30%
            min(contrast / 50, 1.0) * 0.3  # 对比度权重30%
        )
        
        return min(quality_score, 1.0)
    
    def get_quality_level(self, quality_score: float) -> str:
        """根据质量分数获取质量等级"""
        if quality_score >= 0.8:
            return 'good'
        elif quality_score >= 0.5:
            return 'fair'
        else:
            return 'poor'
    
    def save_image(self, image_array: np.ndarray, upload_dir: str, filename: str) -> str:
        """保存图像到磁盘"""
        print(f"=== 开始保存图像 ===")
        print(f"目标目录: {upload_dir}")
        print(f"文件名: {filename}")
        print(f"图像形状: {image_array.shape}")
        
        # 检查并创建目录
        if not os.path.exists(upload_dir):
            print(f"创建目录: {upload_dir}")
            try:
                os.makedirs(upload_dir, exist_ok=True)
                print(f"目录创建成功")
            except Exception as e:
                print(f"目录创建失败: {e}")
                raise ValueError(f"无法创建目录 {upload_dir}: {e}")
        else:
            print(f"目录已存在")
        
        # 构建完整路径
        image_path = os.path.join(upload_dir, filename)
        print(f"完整路径: {image_path}")
        print(f"路径编码: {image_path.encode('utf-8')[:50]}...")
        
        # 转换为BGR格式（OpenCV格式）
        print(f"转换图像格式...")
        image_bgr = cv2.cvtColor(image_array, cv2.COLOR_RGB2BGR)
        print(f"转换后形状: {image_bgr.shape}")
        
        # 尝试保存
        print(f"尝试保存图像...")
        success = cv2.imwrite(image_path, image_bgr)
        print(f"OpenCV保存结果: {success}")
        
        if not success:
            print(f"OpenCV保存失败，尝试PIL保存...")
            try:
                from PIL import Image as PILImage
                # 转换回RGB
                image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
                pil_image = PILImage.fromarray(image_rgb)
                
                # 使用PIL保存
                pil_image.save(image_path, 'PNG', quality=95)
                print(f"PIL保存成功")
                
                # 验证文件是否真的保存了
                if os.path.exists(image_path):
                    file_size = os.path.getsize(image_path)
                    print(f"验证成功，文件大小: {file_size} 字节")
                else:
                    raise ValueError("PIL保存后文件不存在")
                    
            except Exception as e:
                print(f"PIL保存也失败: {e}")
                raise ValueError(f"无法保存图像到 {image_path}: {e}")
        else:
            # 验证保存是否成功
            if os.path.exists(image_path):
                file_size = os.path.getsize(image_path)
                print(f"验证成功，文件大小: {file_size} 字节")
            else:
                print(f"保存返回True但文件不存在")
                raise ValueError(f"图像保存失败: {image_path}")
        
        print(f"=== 图像保存完成 ===")
        print(f"保存路径: {image_path}")
        return image_path
    
    def get_image_info(self, image_path: str) -> Dict[str, Any]:
        """获取图像信息"""
        image = cv2.imread(image_path)
        if image is None:
            raise ValueError(f"无法读取图像: {image_path}")
        
        height, width, channels = image.shape
        file_size = os.path.getsize(image_path)
        
        # 计算图像哈希值
        with open(image_path, 'rb') as f:
            file_hash = hashlib.sha256(f.read()).hexdigest()
        
        return {
            'width': width,
            'height': height,
            'channels': channels,
            'file_size': file_size,
            'file_hash': file_hash
        }