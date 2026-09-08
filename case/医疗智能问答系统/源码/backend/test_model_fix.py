#!/usr/bin/env python3
import sys
sys.path.append('.')
from services.model_manager import ModelManager
from services.image_processor import ImageProcessor

print('=== 测试修复后的模型预测功能 ===')
try:
    # 创建图像处理器
    image_processor = ImageProcessor()
    
    # 加载测试图像
    test_image_path = 'uploads/images/931a2e71-8656-49ad-8300-6b72a6fb3ca6.png'
    if not __import__('os').path.exists(test_image_path):
        print(f'测试图像不存在: {test_image_path}')
        exit(1)
    
    print(f'找到测试图像: {test_image_path}')
    
    # 处理图像
    result = image_processor.preprocess_uploaded_image(test_image_path)
    processed_image = result['processed_image']
    print(f'图像处理成功，形状: {processed_image.shape}')
    
    # 创建模型管理器
    model_manager = ModelManager()
    print(f'可用模型: {list(model_manager.models.keys())}')
    
    # 测试单个模型预测
    print()
    print('=== 测试单个模型预测 ===')
    for model_name in ['efficientnet_b3']:
        if model_name in model_manager.models:
            try:
                pred = model_manager.predict_single_model(model_name, processed_image)
                print(f'✅ {model_name} 预测成功:')
                print('  预测类别:', pred['predicted_class'])
                confidence = pred['confidence']
                print('  置信度:', f'{confidence:.4f}')
                print('  各类别概率:', pred['class_probabilities'])
            except Exception as e:
                print(f'❌ {model_name} 预测失败: {str(e)}')
                import traceback
                print('详细错误:', traceback.format_exc())
        else:
            print(f'❌ 模型 {model_name} 不在可用列表中')
    
    # 测试集成预测
    print()
    print('=== 测试集成预测 ===')
    try:
        ensemble_result = model_manager.ensemble_predict(processed_image, ['efficientnet_b3'])
        print(f'✅ 集成预测成功:')
        final_pred = ensemble_result['ensemble_prediction']
        print('  最终预测:', final_pred['predicted_class'])
        confidence = final_pred['confidence']
        print('  最终置信度:', f'{confidence:.4f}')
        print('  使用模型:', ensemble_result['models_used'])
    except Exception as e:
        print(f'❌ 集成预测失败: {str(e)}')
        import traceback
        print('详细错误:', traceback.format_exc())
    
    print('\n=== 测试完成 ===')
    
except Exception as e:
    print(f'❌ 测试过程失败: {str(e)}')
    import traceback
    print('详细错误:', traceback.format_exc())