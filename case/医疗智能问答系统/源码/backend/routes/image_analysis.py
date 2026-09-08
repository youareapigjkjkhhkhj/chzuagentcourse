#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
图像分析API路由
"""

import os
import time
import uuid
import base64
from datetime import datetime
from typing import List, Dict
from flask import Blueprint, request, jsonify, current_app
from werkzeug.utils import secure_filename
from models import db
from models.image_analysis import ImageAnalysis, AnalysisResult, ModelPrediction, DiagnosisReport
from services.image_processor import ImageProcessor
from services.model_manager import ModelManager
from utils.response import error_response, success_response
import json

# 创建蓝图
analysis_bp = Blueprint('analysis', __name__, url_prefix='/api/analysis')

# 初始化服务
image_processor = ImageProcessor()
model_manager = ModelManager()

# 允许的图像文件扩展名
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'bmp', 'tiff'}

def allowed_file(filename):
    """检查文件扩展名是否允许"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@analysis_bp.route('/upload', methods=['POST'])
def upload_image():
    """上传图像接口"""
    try:
        # 检查是否有文件
        if 'image' not in request.files:
            return error_response('没有上传文件')
        
        file = request.files['image']
        if file.filename == '':
            return error_response('没有选择文件')
        
        if not allowed_file(file.filename):
            return error_response('不支持的文件格式，仅支持 PNG, JPG, JPEG, BMP, TIFF')
        
        # 生成唯一ID和文件名
        analysis_id = str(uuid.uuid4())
        filename = secure_filename(file.filename)
        file_ext = filename.rsplit('.', 1)[1].lower()
        new_filename = f"{analysis_id}.{file_ext}"
        
        # 处理图像
        image_data = image_processor.preprocess_uploaded_image(file)
        
        # 保存图像
        upload_dir = os.path.join(current_app.root_path, 'uploads', 'images')
        image_path = image_processor.save_image(
            image_data['original_image'], 
            upload_dir, 
            new_filename
        )
        
        # 创建图像分析记录
        image_analysis = ImageAnalysis(
            id=analysis_id,
            image_filename=filename,
            image_path=image_path,
            image_hash=image_data['image_hash'],
            image_size=len(file.read()),
            image_format=file_ext,
            analysis_status='pending'
        )
        file.seek(0)  # 重置文件指针
        
        db.session.add(image_analysis)
        db.session.commit()
        
        return success_response({
            'analysis_id': analysis_id,
            'image_url': f'/uploads/images/{new_filename}',
            'image_quality': image_data['quality_level'],
            'quality_score': image_data['quality_score'],
            'message': '图像上传成功'
        })
        
    except Exception as e:
        db.session.rollback()
        return error_response(f'图像上传失败: {str(e)}', 500)

@analysis_bp.route('/start', methods=['POST'])
def start_analysis_complete():
    """开始完整分析接口（上传+分析一步完成）"""
    try:
        print(f"Request files: {list(request.files.keys())}")
        print(f"Request form: {list(request.form.keys())}")
        
        image_data = None
        image_filename = 'uploaded_image.jpg'  # 默认文件名
        
        # 检查是否有文件上传
        if 'image' in request.files:
            # 二进制文件上传
            file = request.files['image']
            if file.filename == '':
                return error_response('没有选择文件')
            
            if not allowed_file(file.filename):
                return error_response('不支持的文件格式，仅支持 PNG, JPG, JPEG, BMP, TIFF')
            
            image_filename = secure_filename(file.filename)
            
            # 临时保存文件以便处理
            # 计算正确的项目根目录路径（从routes目录向上两级）
            script_dir = os.path.dirname(os.path.abspath(__file__))  # routes目录
            project_root = os.path.dirname(script_dir)  # backend目录
            temp_dir = os.path.join(project_root, 'uploads', 'temp')
            if not os.path.exists(temp_dir):
                os.makedirs(temp_dir)
            
            analysis_id = str(uuid.uuid4())
            file_ext = image_filename.rsplit('.', 1)[1].lower()
            temp_path = os.path.join(temp_dir, f"temp_{analysis_id}.{file_ext}")
            file.save(temp_path)
            print(f"Saved file to temp: {temp_path}")
            print(f"Project root: {project_root}")
            
        elif 'image' in request.form:
            # 字符串数据上传（可能是base64或图片URL）
            image_data = request.form.get('image')
            print(f"Received image data as string, length: {len(image_data)}")
            
            # 如果是base64数据
            if image_data.startswith('data:image/'):
                # 提取base64数据
                base64_data = image_data.split(',')[1]
                image_bytes = base64.b64decode(base64_data)
                
                # 确定文件扩展名
                if 'image/jpeg' in image_data:
                    file_ext = 'jpg'
                elif 'image/png' in image_data:
                    file_ext = 'png'
                else:
                    file_ext = 'jpg'  # 默认
                    
                image_filename = f"uploaded_image.{file_ext}"
                
                # 临时保存文件
                # 计算正确的项目根目录路径（从routes目录向上两级）
                script_dir = os.path.dirname(os.path.abspath(__file__))  # routes目录
                project_root = os.path.dirname(script_dir)  # backend目录
                temp_dir = os.path.join(project_root, 'uploads', 'temp')
                if not os.path.exists(temp_dir):
                    os.makedirs(temp_dir)
                
                analysis_id = str(uuid.uuid4())
                temp_path = os.path.join(temp_dir, f"temp_{analysis_id}.{file_ext}")
                with open(temp_path, 'wb') as f:
                    f.write(image_bytes)
                    
                print(f"Saved base64 image to temp: {temp_path}")
                
            else:
                return error_response('不支持的图片数据格式')
                
        else:
            return error_response('没有上传图片')
        
        # 获取其他参数
        patient_id = request.form.get('patient_id', '')
        patient_name = request.form.get('patient_name', '')
        model_type = request.form.get('model_type', 'ensemble')
        
        # 获取选中的模型列表（前端传递的selected_models字段）
        selected_models = []
        selected_models_param = request.form.get('selected_models', '')
        if selected_models_param:
            try:
                selected_models = json.loads(selected_models_param)
            except json.JSONDecodeError:
                selected_models = []
        
        print(f"Processing analysis: patient={patient_name}, model_type={model_type}")
        
        # 处理图像
        image_data = image_processor.preprocess_uploaded_image(temp_path)
        print(f"Image processed: shape={image_data['processed_image'].shape}, quality={image_data['quality_level']}")
        
        # 保存图像到正式位置
        # 计算正确的项目根目录路径（从routes目录向上两级）
        script_dir = os.path.dirname(os.path.abspath(__file__))  # routes目录
        project_root = os.path.dirname(script_dir)  # backend目录
        upload_dir = os.path.join(project_root, 'uploads', 'images')
        image_path = image_processor.save_image(
            image_data['original_image'], 
            upload_dir, 
            f"{analysis_id}.{file_ext}"
        )
        print(f"Saved final image to: {image_path}")
        
        # 获取文件大小
        file_size = os.path.getsize(image_path)
        
        # 检查是否已存在相同哈希值的图像分析记录
        existing_analysis = ImageAnalysis.query.filter_by(image_hash=image_data['image_hash']).first()
        
        if existing_analysis:
            print(f"发现重复图像: {image_data['image_hash']}")
            
            # 如果现有记录已完成分析，返回现有结果
            if existing_analysis.analysis_status == 'completed':
                print("返回现有分析结果")
                
                # 清理临时文件
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                
                # 清理新保存的文件（因为不需要）
                if os.path.exists(image_path):
                    os.remove(image_path)
                
                # 获取现有分析结果
                analysis_results = AnalysisResult.query.filter_by(image_analysis_id=existing_analysis.id).all()
                results = []
                for result in analysis_results:
                    results.append({
                        'model': result.model_name,
                        'level': result.prediction_level,
                        'confidence': result.confidence_score,
                        'features': [
                            {
                                'id': 1,
                                'name': '病理特征检测',
                                'description': f'检测到 {get_diagnosis_level_name(result.prediction_level)} 相关特征',
                                'confidence': result.confidence_score,
                                'location': '眼底区域'
                            }
                        ]
                    })
                
                # 获取诊断报告
                diagnosis_report = DiagnosisReport.query.filter_by(image_analysis_id=existing_analysis.id).first()
                
                return success_response({
                    'analysis_id': existing_analysis.id,
                    'results': results,
                    'final_diagnosis': {
                        'level': diagnosis_report.ensemble_diagnosis_level,
                        'level_name': get_diagnosis_level_name(diagnosis_report.ensemble_diagnosis_level),
                        'confidence': diagnosis_report.ensemble_confidence
                    },
                    'processing_time': 0,  # 使用现有结果，处理时间为0
                    'image_quality': analysis_results[0].image_quality if analysis_results else 'good',
                    'recommendations': json.loads(diagnosis_report.recommendations) if diagnosis_report else [],
                    'models_used': [result.model_name for result in analysis_results]
                })
            
            elif existing_analysis.analysis_status == 'processing':
                # 如果正在分析中，返回分析ID供前端查询状态
                print("图像正在分析中，返回现有分析ID")
                
                # 清理临时文件
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                
                # 清理新保存的文件
                if os.path.exists(image_path):
                    os.remove(image_path)
                
                return success_response({
                    'analysis_id': existing_analysis.id,
                    'status': 'processing',
                    'message': '图像正在分析中，请稍后查询结果'
                })
            
            else:
                # 如果分析失败，允许重新分析，删除现有记录
                print("现有分析失败，允许重新分析")
                db.session.delete(existing_analysis)
                db.session.commit()
        
        # 创建新的图像分析记录
        image_analysis = ImageAnalysis(
            id=analysis_id,
            image_filename=image_filename,
            image_path=image_path,
            image_hash=image_data['image_hash'],
            image_size=file_size,
            image_format=file_ext,
            analysis_status='processing'
        )
        
        # 清理临时文件
        if os.path.exists(temp_path):
            os.remove(temp_path)
        
        db.session.add(image_analysis)
        db.session.commit()
        
        # 进行模型预测
        # 注意：selected_models 已经在前面从请求参数中获取，这里不需要重新设置
        processed_image = image_data['processed_image']
        image_quality = image_data['quality_level']
        
        if model_type == 'ensemble':
            # 集成模型预测
            ensemble_result = model_manager.ensemble_predict(
                processed_image.unsqueeze(0), 
                selected_models if selected_models else None
            )
            
            if ensemble_result is None:
                print("Error: ensemble_predict returned None")
                return error_response('模型预测失败：集成结果为空', 500)
                
            print(f"Ensemble result: {ensemble_result}")
            print(f"Individual predictions: {ensemble_result.get('individual_predictions', {})}")
            
            # 保存单个模型的预测结果
            analysis_results = []
            for model_name, prediction in ensemble_result['individual_predictions'].items():
                # 保存分析结果
                analysis_result = AnalysisResult(
                    image_analysis_id=analysis_id,
                    model_name=model_name,
                    prediction_level=prediction['predicted_class'],
                    confidence_score=prediction['confidence'],
                    processing_time=prediction['processing_time'],
                    image_quality=image_quality
                )
                db.session.add(analysis_result)
                db.session.flush()  # 获取ID
                
                # 保存模型预测详细结果
                model_pred = ModelPrediction(
                    analysis_result_id=analysis_result.id,
                    class_0_prob=prediction['class_probabilities']['0'],
                    class_1_prob=prediction['class_probabilities']['1'],
                    class_2_prob=prediction['class_probabilities']['2'],
                    class_3_prob=prediction['class_probabilities']['3'],
                    class_4_prob=prediction['class_probabilities']['4'],
                    raw_prediction=json.dumps(prediction)
                )
                db.session.add(model_pred)
                
                analysis_results.append(analysis_result)
            
            # 最终结果
            final_result = ensemble_result['ensemble_prediction']
            total_processing_time = ensemble_result['total_processing_time']
            
        else:
            # 单模型预测
            selected_model = model_type
            if selected_model not in model_manager.get_available_models():
                return error_response(f'模型 {selected_model} 不可用')
            
            single_result = model_manager.predict_single_model(selected_model, processed_image.unsqueeze(0))
            
            if single_result is None:
                print(f"Error: predict_single_model returned None for {selected_model}")
                return error_response(f'模型 {selected_model} 预测失败', 500)
                
            print(f"Single result for {selected_model}: {single_result}")
            
            # 保存分析结果
            analysis_result = AnalysisResult(
                image_analysis_id=analysis_id,
                model_name=selected_model,
                prediction_level=single_result['predicted_class'],
                confidence_score=single_result['confidence'],
                processing_time=single_result['processing_time'],
                image_quality=image_quality
            )
            db.session.add(analysis_result)
            db.session.flush()
            
            # 保存模型预测详细结果
            model_pred = ModelPrediction(
                analysis_result_id=analysis_result.id,
                class_0_prob=single_result['class_probabilities']['0'],
                class_1_prob=single_result['class_probabilities']['1'],
                class_2_prob=single_result['class_probabilities']['2'],
                class_3_prob=single_result['class_probabilities']['3'],
                class_4_prob=single_result['class_probabilities']['4'],
                raw_prediction=json.dumps(single_result)
            )
            db.session.add(model_pred)
            
            analysis_results = [analysis_result]
            final_result = {
                'predicted_class': single_result['predicted_class'],
                'confidence': single_result['confidence'],
                'class_probabilities': single_result['class_probabilities']
            }
            total_processing_time = single_result['processing_time']
        
        # 更新图像分析状态为完成
        image_analysis.analysis_status = 'completed'
        db.session.commit()
        
        # 生成建议
        print(f"Generating recommendations for level: {final_result['predicted_class']}")
        recommendations = generate_recommendations(final_result['predicted_class'])
        print(f"Generated recommendations: {recommendations}")
        print(f"Recommendations type: {type(recommendations)}")
        
        # 构建返回结果
        results = []
        for result in analysis_results:
            results.append({
                'model': result.model_name,
                'level': result.prediction_level,
                'confidence': result.confidence_score,
                'features': [
                    {
                        'id': 1,
                        'name': '病理特征检测',
                        'description': f'检测到 {get_diagnosis_level_name(result.prediction_level)} 相关特征',
                        'confidence': result.confidence_score,
                        'location': '眼底区域'
                    }
                ]
            })
        
        # 确定使用的模型
        if model_type == 'ensemble':
            models_used = ensemble_result.get('models_used', [result.model_name for result in analysis_results])
        else:
            models_used = [model_type]
        
        # 创建诊断报告
        diagnosis_report = DiagnosisReport(
            image_analysis_id=analysis_id,
            patient_id=patient_id,
            patient_name=patient_name,
            ensemble_diagnosis_level=final_result['predicted_class'],
            ensemble_confidence=final_result['confidence'],
            report_content=json.dumps({
                'analysis_id': analysis_id,
                'results': results,
                'image_quality': image_quality,
                'processing_time': total_processing_time
            }),
            recommendations=json.dumps(recommendations),
            risk_level=calculate_risk_level(final_result['predicted_class'], final_result['confidence'])
        )
        db.session.add(diagnosis_report)
        
        return success_response({
            'analysis_id': analysis_id,
            'results': results,
            'final_diagnosis': {
                'level': final_result['predicted_class'],
                'level_name': get_diagnosis_level_name(final_result['predicted_class']),
                'confidence': final_result['confidence']
            },
            'processing_time': total_processing_time,
            'image_quality': image_quality,
            'recommendations': recommendations,
            'models_used': models_used
        })
        
    except Exception as e:
        import traceback
        print(f"Error in start_analysis_complete: {str(e)}")
        print(f"Traceback: {traceback.format_exc()}")
        
        # 更新状态为失败
        try:
            if 'analysis_id' in locals():
                image_analysis = ImageAnalysis.query.get(analysis_id)
                if image_analysis:
                    image_analysis.analysis_status = 'failed'
                    db.session.commit()
        except:
            pass
        
        db.session.rollback()
        return error_response(f'图像分析失败: {str(e)}', 500)

@analysis_bp.route('/<analysis_id>/status', methods=['GET'])
def get_analysis_status(analysis_id):
    """获取分析状态接口"""
    try:
        image_analysis = ImageAnalysis.query.get_or_404(analysis_id)
        
        return success_response({
            'analysis_id': analysis_id,
            'status': image_analysis.analysis_status,
            'created_at': image_analysis.created_at.isoformat() if image_analysis.created_at else None,
            'updated_at': image_analysis.updated_at.isoformat() if image_analysis.updated_at else None
        })
        
    except Exception as e:
        return error_response(f'获取分析状态失败: {str(e)}', 404)

@analysis_bp.route('/<analysis_id>/analyze', methods=['POST'])
def start_analysis(analysis_id):
    """开始图像分析接口"""
    try:
        # 获取图像分析记录
        image_analysis = ImageAnalysis.query.get_or_404(analysis_id)
        
        if image_analysis.analysis_status == 'completed':
            return error_response('图像已经分析完成')
        
        if image_analysis.analysis_status == 'processing':
            return error_response('图像正在分析中')
        
        # 更新状态为处理中
        image_analysis.analysis_status = 'processing'
        db.session.commit()
        
        # 获取请求参数
        data = request.get_json() or {}
        model_type = data.get('model_type', 'ensemble')  # ensemble 或具体模型名
        model_names = data.get('model_names', None)  # 指定模型列表
        
        # 读取图像并处理
        with open(image_analysis.image_path, 'rb') as f:
            image_data = image_processor.preprocess_uploaded_image(f)
        
        processed_image = image_data['processed_image']
        image_quality = image_data['quality_level']
        
        # 进行模型预测
        if model_type == 'ensemble':
            # 集成模型预测
            ensemble_result = model_manager.ensemble_predict(
                processed_image.unsqueeze(0), 
                model_names
            )
            
            # 保存单个模型的预测结果
            analysis_results = []
            for model_name, prediction in ensemble_result['individual_predictions'].items():
                # 保存分析结果
                analysis_result = AnalysisResult(
                    image_analysis_id=analysis_id,
                    model_name=model_name,
                    prediction_level=prediction['predicted_class'],
                    confidence_score=prediction['confidence'],
                    processing_time=prediction['processing_time'],
                    image_quality=image_quality
                )
                db.session.add(analysis_result)
                db.session.flush()  # 获取ID
                
                # 保存模型预测详细结果
                model_pred = ModelPrediction(
                    analysis_result_id=analysis_result.id,
                    class_0_prob=prediction['class_probabilities']['0'],
                    class_1_prob=prediction['class_probabilities']['1'],
                    class_2_prob=prediction['class_probabilities']['2'],
                    class_3_prob=prediction['class_probabilities']['3'],
                    class_4_prob=prediction['class_probabilities']['4'],
                    raw_prediction=json.dumps(prediction)
                )
                db.session.add(model_pred)
                
                analysis_results.append(analysis_result)
            
            # 最终结果
            final_result = ensemble_result['ensemble_prediction']
            total_processing_time = ensemble_result['total_processing_time']
            
        else:
            # 单模型预测
            if model_type not in model_manager.get_available_models():
                return error_response(f'模型 {model_type} 不可用')
            
            single_result = model_manager.predict_single_model(model_type, processed_image.unsqueeze(0))
            
            # 保存分析结果
            analysis_result = AnalysisResult(
                image_analysis_id=analysis_id,
                model_name=model_type,
                prediction_level=single_result['predicted_class'],
                confidence_score=single_result['confidence'],
                processing_time=single_result['processing_time'],
                image_quality=image_quality
            )
            db.session.add(analysis_result)
            db.session.flush()
            
            # 保存模型预测详细结果
            model_pred = ModelPrediction(
                analysis_result_id=analysis_result.id,
                class_0_prob=single_result['class_probabilities']['0'],
                class_1_prob=single_result['class_probabilities']['1'],
                class_2_prob=single_result['class_probabilities']['2'],
                class_3_prob=single_result['class_probabilities']['3'],
                class_4_prob=single_result['class_probabilities']['4'],
                raw_prediction=json.dumps(single_result)
            )
            db.session.add(model_pred)
            
            analysis_results = [analysis_result]
            final_result = {
                'predicted_class': single_result['predicted_class'],
                'confidence': single_result['confidence'],
                'class_probabilities': single_result['class_probabilities']
            }
            total_processing_time = single_result['processing_time']
        
        # 更新图像分析状态为完成
        image_analysis.analysis_status = 'completed'
        db.session.commit()
        
        # 生成建议
        print(f"Generating recommendations for level: {final_result['predicted_class']}")
        recommendations = generate_recommendations(final_result['predicted_class'])
        print(f"Generated recommendations: {recommendations}")
        print(f"Recommendations type: {type(recommendations)}")
        
        return success_response({
            'analysis_id': analysis_id,
            'final_diagnosis': {
                'level': final_result['predicted_class'],
                'level_name': get_diagnosis_level_name(final_result['predicted_class']),
                'confidence': final_result['confidence']
            },
            'individual_results': [result.to_dict() for result in analysis_results],
            'processing_time': total_processing_time,
            'image_quality': image_quality,
            'recommendations': recommendations,
            'models_used': ensemble_result.get('models_used', [model_type]) if model_type == 'ensemble' else [model_type]
        })
        
    except Exception as e:
        # 更新状态为失败
        try:
            image_analysis = ImageAnalysis.query.get(analysis_id)
            if image_analysis:
                image_analysis.analysis_status = 'failed'
                db.session.commit()
        except:
            pass
        
        db.session.rollback()
        return error_response(f'图像分析失败: {str(e)}', 500)

@analysis_bp.route('/<analysis_id>/results', methods=['GET'])
def get_analysis_results(analysis_id):
    """获取分析结果接口"""
    try:
        # 获取图像分析记录
        image_analysis = ImageAnalysis.query.get_or_404(analysis_id)
        
        # 获取所有分析结果
        analysis_results = AnalysisResult.query.filter_by(image_analysis_id=analysis_id).all()
        
        if not analysis_results:
            return error_response('没有找到分析结果')
        
        results_data = []
        for result in analysis_results:
            result_dict = result.to_dict()
            
            model_pred = ModelPrediction.query.filter_by(analysis_result_id=result.id).first()
            if model_pred:
                model_pred_dict = model_pred.to_dict()
                level_name = get_diagnosis_level_name(result.prediction_level)
                features = [
                    {
                        'id': f'{result.id}-feature-1',
                        'name': '病理特征检测',
                        'description': f'检测到 {level_name} 相关特征',
                        'confidence': result.confidence_score,
                        'location': '眼底区域'
                    }
                ]
                model_pred_dict['features'] = features
                result_dict['model_prediction'] = model_pred_dict
            
            results_data.append(result_dict)
        
        # 如果有多个结果，计算集成结果
        if len(results_data) > 1:
            ensemble_result = calculate_ensemble_result(results_data)
        else:
            ensemble_result = {
                'level': results_data[0]['prediction_level'],
                'confidence': results_data[0]['confidence_score'],
                'level_name': get_diagnosis_level_name(results_data[0]['prediction_level'])
            }
        
        return success_response({
            'analysis_id': analysis_id,
            'image_analysis': image_analysis.to_dict(),
            'analysis_results': results_data,
            'final_diagnosis': ensemble_result,
            'status': image_analysis.analysis_status
        })
        
    except Exception as e:
        return error_response(f'获取分析结果失败: {str(e)}')

@analysis_bp.route('/history', methods=['GET'])
def get_analysis_history():
    """获取分析历史记录"""
    try:
        from sqlalchemy import desc
        
        # 获取查询参数
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 10, type=int)
        patient_id = request.args.get('patient_id')
        date_from = request.args.get('date_from')
        date_to = request.args.get('date_to')
        
        # 构建查询
        query = db.session.query(ImageAnalysis).join(
            AnalysisResult, ImageAnalysis.id == AnalysisResult.image_analysis_id
        ).join(
            DiagnosisReport, ImageAnalysis.id == DiagnosisReport.image_analysis_id
        )
        
        # 添加过滤条件
        if patient_id:
            query = query.filter(DiagnosisReport.patient_id == patient_id)
        
        if date_from:
            query = query.filter(ImageAnalysis.created_at >= date_from)
        
        if date_to:
            query = query.filter(ImageAnalysis.created_at <= date_to)
        
        # 按创建时间降序排列
        query = query.order_by(desc(ImageAnalysis.created_at))
        
        # 分页
        pagination = query.paginate(
            page=page, 
            per_page=per_page, 
            error_out=False
        )
        
        # 构建返回数据
        histories = []
        for image_analysis in pagination.items:
            # 获取最新的分析结果
            latest_result = AnalysisResult.query.filter_by(
                image_analysis_id=image_analysis.id
            ).order_by(desc(AnalysisResult.created_at)).first()
            
            # 获取诊断报告
            diagnosis_report = DiagnosisReport.query.filter_by(
                image_analysis_id=image_analysis.id
            ).first()
            
            if latest_result and diagnosis_report:
                histories.append({
                    'id': image_analysis.id,
                    'report_id': diagnosis_report.id,  # 添加报告ID
                    'patient_id': diagnosis_report.patient_id,
                    'patient_name': diagnosis_report.patient_name,
                    'image_filename': image_analysis.image_filename,
                    'status': image_analysis.analysis_status,
                    'diagnosis_level': latest_result.prediction_level,
                    'confidence': latest_result.confidence_score,
                    'model_name': latest_result.model_name,
                    'created_at': image_analysis.created_at.isoformat() if image_analysis.created_at else None,
                    'diagnosis_level_name': get_diagnosis_level_name(latest_result.prediction_level)
                })
        
        return success_response({
            'histories': histories,
            'total': pagination.total,
            'page': page,
            'per_page': per_page,
            'pages': pagination.pages
        })
        
    except Exception as e:
        current_app.logger.error(f"获取分析历史失败: {str(e)}")
        return error_response(f'获取分析历史失败: {str(e)}', 500)

@analysis_bp.route('/models', methods=['GET'])
def get_available_models():
    """获取可用模型列表"""
    try:
        # 获取模型管理器信息
        model_info = model_manager.get_model_info()
        available_models = model_info.get('available_models', [])
        
        # 构建前端期望的模型详情数组
        models_detail = []
        model_descriptions = {
            'efficientnet_b3': {
                'name': 'EfficientNet-B3',
                'type': '图像分类',
                'description': '高效卷积神经网络，具有出色的准确性和计算效率'
            },
            'resnet50': {
                'name': 'ResNet-50',
                'type': '图像分类',
                'description': '深度残差网络，擅长识别复杂的图像特征'
            },
            'densenet121': {
                'name': 'DenseNet-121',
                'type': '图像分类',
                'description': '密集连接网络，能够高效利用特征信息'
            },
            'efficientnet_b5': {
                'name': 'EfficientNet-B5',
                'type': '图像分类',
                'description': '增强版高效网络，提供更高的识别精度'
            },
            'resnet152': {
                'name': 'ResNet-152',
                'type': '图像分类',
                'description': '更深的残差网络，适合复杂的图像分析任务'
            },
            'efficientnet_b8': {
                'name': 'EfficientNet-B8',
                'type': '图像分类',
                'description': '高分辨率模型，专注于精细特征识别'
            }
        }
        
        for model_name in available_models:
            model_info = model_descriptions.get(model_name, {
                'name': model_name,
                'type': '图像分类',
                'description': '深度学习模型'
            })
            
            # 构建前端期望的完整模型信息
            model_detail = {
                'id': f'ai-model-{model_name}',
                'name': model_info['name'],
                'modelName': model_name,  # 这是前端主要使用的字段
                'provider': 'local',  # 统一的本地AI模型提供商
                'type': model_info['type'],
                'status': 'active',  # 模型都是活跃状态
                'isDefault': model_name == 'resnet50',  # 默认选择 ResNet-50
                'description': model_info['description'],
                'createdAt': '2024-01-01T00:00:00Z',
                'updatedAt': '2024-01-01T00:00:00Z'
            }
            models_detail.append(model_detail)
        
        return success_response({
            'models': models_detail,
            'total': len(models_detail)
        })
    except Exception as e:
        current_app.logger.error(f"获取模型信息失败: {str(e)}")
        return error_response(f'获取模型信息失败: {str(e)}')

@analysis_bp.route('/stats', methods=['GET'])
def get_analysis_stats():
    """获取分析统计信息"""
    try:
        from datetime import datetime, date, timedelta
        from sqlalchemy import func, and_
        from models.user import User
        from models.image_analysis import ImageAnalysis, AnalysisResult
        
        # 获取总报告数
        total_reports = db.session.query(func.count(ImageAnalysis.id)).scalar() or 0
        
        # 获取高风险病例数 (级别3和4)
        high_risk_cases = db.session.query(func.count(AnalysisResult.id)).join(
            ImageAnalysis, AnalysisResult.image_analysis_id == ImageAnalysis.id
        ).filter(
            AnalysisResult.prediction_level.in_([3, 4])
        ).scalar() or 0
        
        # 获取活跃用户数 (最近30天有登录的用户)
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        active_users = db.session.query(func.count(User.id)).filter(
            User.is_active == True,
            User.last_login >= thirty_days_ago
        ).scalar() or 0
        
        # 获取今日报告数
        today = date.today()
        daily_reports = db.session.query(func.count(ImageAnalysis.id)).filter(
            func.date(ImageAnalysis.created_at) == today
        ).scalar() or 0
        
        # 获取诊断结果分布
        diagnosis_distribution = []
        
        # 数字级别到字符串级别的映射
        level_mapping = {
            0: 'NoDR',
            1: 'Mild', 
            2: 'Moderate',
            3: 'Severe',
            4: 'Proliferative'
        }
        
        for level in range(5):
            count = db.session.query(func.count(AnalysisResult.id)).join(
                ImageAnalysis, AnalysisResult.image_analysis_id == ImageAnalysis.id
            ).filter(
                AnalysisResult.prediction_level == level
            ).scalar() or 0
            
            percentage = (count / total_reports * 100) if total_reports > 0 else 0
            
            diagnosis_distribution.append({
                'level': level_mapping[level],  # 使用字符串级别
                'count': count,
                'percentage': round(percentage, 2)
            })
        
        stats = {
            'totalReports': total_reports,
            'highRiskCases': high_risk_cases,
            'activeUsers': active_users,
            'dailyReports': daily_reports,
            'diagnosisDistribution': diagnosis_distribution
        }
        
        return success_response({
            'stats': stats
        })
        
    except Exception as e:
        current_app.logger.error(f"获取分析统计信息失败: {str(e)}")
        return error_response(f'获取统计信息失败: {str(e)}', 500)

def get_diagnosis_level_name(level: int) -> str:
    """获取诊断级别名称"""
    level_names = {
        0: '无糖尿病视网膜病变',
        1: '轻度非增殖性糖尿病视网膜病变',
        2: '中度非增殖性糖尿病视网膜病变',
        3: '重度非增殖性糖尿病视网膜病变',
        4: '增殖性糖尿病视网膜病变'
    }
    return level_names.get(level, '未知')

def calculate_ensemble_result(results: List[Dict]) -> Dict:
    """计算集成结果"""
    if not results:
        return {}
    
    # 简单的平均集成
    total_confidence = sum(result['confidence_score'] for result in results)
    avg_confidence = total_confidence / len(results)
    
    # 找出最常见的预测级别
    level_counts = {}
    for result in results:
        level = result['prediction_level']
        level_counts[level] = level_counts.get(level, 0) + 1
    
    final_level = max(level_counts.items(), key=lambda x: x[1])[0]
    
    return {
        'level': final_level,
        'confidence': avg_confidence,
        'level_name': get_diagnosis_level_name(final_level)
    }

def generate_recommendations(diagnosis_level: int) -> List[str]:
    """根据诊断级别生成建议"""
    try:
        recommendations = {
            0: [
                '继续保持良好的血糖控制',
                '定期进行眼底检查（每年1次）',
                '注意眼部卫生，避免眼部感染'
            ],
            1: [
                '加强血糖控制，定期监测血糖',
                '每6个月进行眼底检查',
                '控制血压和血脂',
                '建议咨询眼科医生'
            ],
            2: [
                '严格控制血糖，必要时调整治疗方案',
                '每3-4个月进行眼底检查',
                '积极控制相关并发症',
                '建议尽早进行眼科治疗'
            ],
            3: [
                '立即就诊眼科专科',
                '考虑激光治疗或其他干预措施',
                '密切监测病情变化',
                '多学科综合治疗'
            ],
            4: [
                '紧急眼科会诊',
                '可能需要手术治疗',
                '密切监测视力变化',
                '全面的糖尿病并发症管理'
            ]
        }
        
        result = recommendations.get(diagnosis_level, ['建议咨询医生进行进一步检查'])
        print(f"generate_recommendations: level={diagnosis_level}, result={result}")
        return result
        
    except Exception as e:
        print(f"Error in generate_recommendations: {str(e)}")
        return ['建议咨询医生进行进一步检查']

def calculate_risk_level(diagnosis_level: int, confidence: float) -> str:
    """根据诊断级别和置信度计算风险等级"""
    # 基础风险等级由诊断级别决定
    base_risk = {
        0: 'low',
        1: 'low', 
        2: 'medium',
        3: 'high',
        4: 'critical'
    }
    
    base_level = base_risk.get(diagnosis_level, 'medium')
    
    # 如果置信度很高，可能提升风险等级
    if confidence > 0.9 and diagnosis_level >= 2:
        if base_level == 'medium':
            return 'high'
        elif base_level == 'high':
            return 'critical'
    
    return base_level


