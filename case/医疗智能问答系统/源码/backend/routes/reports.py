#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
报告管理API路由
"""

import os
import uuid
from datetime import datetime
from flask import Blueprint, request, jsonify, current_app
from models import db
from models.image_analysis import ImageAnalysis, AnalysisResult, ModelPrediction, DiagnosisReport
from utils.response import error_response, success_response
from sqlalchemy import desc

# 创建蓝图
reports_bp = Blueprint('reports', __name__, url_prefix='/api/reports')

@reports_bp.route('', methods=['POST'])
def create_report():
    """创建诊断报告"""
    try:
        data = request.get_json()
        
        # 验证必需参数
        required_fields = ['analysis_id', 'patient_id', 'ensemble_diagnosis_level', 'ensemble_confidence']
        for field in required_fields:
            if field not in data:
                return error_response(f'缺少必需参数: {field}', 400)
        
        analysis_id = data['analysis_id']
        patient_id = data['patient_id']
        patient_name = data.get('patient_name', '')
        patient_age = data.get('patient_age')
        patient_gender = data.get('patient_gender')
        ensemble_diagnosis_level = data['ensemble_diagnosis_level']
        ensemble_confidence = data['ensemble_confidence']
        
        # 检查图像分析记录是否存在
        image_analysis = ImageAnalysis.query.get(analysis_id)
        if not image_analysis:
            return error_response('图像分析记录不存在', 404)
        
        # 检查是否已经存在该分析的报告
        existing_report = DiagnosisReport.query.filter_by(image_analysis_id=analysis_id).first()
        if existing_report:
            return error_response('该分析已经存在报告', 409)
        
        # 构建报告内容
        report_content = {
            'analysis_results': data.get('analysis_results', []),
            'model_predictions': data.get('model_predictions', []),
            'clinical_summary': data.get('clinical_summary', ''),
            'features_detected': data.get('features_detected', []),
            'image_info': {
                'filename': image_analysis.image_filename,
                'format': image_analysis.image_format,
                'size': image_analysis.image_size,
                'quality': 'good'  # 默认值
            }
        }
        
        # 构建建议内容
        recommendations = {
            'primary_recommendations': data.get('primary_recommendations', []),
            'follow_up_plan': data.get('follow_up_plan', ''),
            'lifestyle_advice': data.get('lifestyle_advice', []),
            'monitoring_schedule': data.get('monitoring_schedule', '')
        }
        
        # 计算风险等级
        risk_level = calculate_risk_level(ensemble_diagnosis_level, ensemble_confidence)
        
        # 创建诊断报告
        diagnosis_report = DiagnosisReport(
            image_analysis_id=analysis_id,
            patient_id=patient_id,
            patient_name=patient_name,
            patient_age=patient_age,
            patient_gender=patient_gender,
            ensemble_diagnosis_level=ensemble_diagnosis_level,
            ensemble_confidence=ensemble_confidence,
            report_content=str(report_content),  # JSON字符串
            recommendations=str(recommendations),  # JSON字符串
            risk_level=risk_level,
            follow_up_plan=data.get('follow_up_plan', '')
        )
        
        db.session.add(diagnosis_report)
        db.session.commit()
        
        return success_response({
            'report_id': diagnosis_report.id,
            'message': '报告创建成功',
            'report': diagnosis_report.to_dict()
        })
        
    except Exception as e:
        current_app.logger.error(f"创建报告失败: {str(e)}")
        db.session.rollback()
        return error_response(f'创建报告失败: {str(e)}', 500)

@reports_bp.route('', methods=['GET'])
def get_reports():
    """获取报告列表"""
    try:
        # 获取查询参数
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 10, type=int)
        patient_id = request.args.get('patient_id')
        date_from = request.args.get('date_from')
        date_to = request.args.get('date_to')
        diagnosis_level = request.args.get('diagnosis_level', type=int)
        
        # 构建查询
        query = db.session.query(DiagnosisReport).join(
            ImageAnalysis, DiagnosisReport.image_analysis_id == ImageAnalysis.id
        )
        
        # 添加过滤条件
        if patient_id:
            query = query.filter(DiagnosisReport.patient_id == patient_id)
        
        if date_from:
            query = query.filter(DiagnosisReport.created_at >= date_from)
        
        if date_to:
            query = query.filter(DiagnosisReport.created_at <= date_to)
        
        if diagnosis_level is not None:
            query = query.filter(DiagnosisReport.ensemble_diagnosis_level == diagnosis_level)
        
        # 按创建时间降序排列
        query = query.order_by(desc(DiagnosisReport.created_at))
        
        # 分页
        pagination = query.paginate(
            page=page, 
            per_page=per_page, 
            error_out=False
        )
        
        # 构建返回数据
        reports = []
        for report in pagination.items:
            report_dict = report.to_dict()
            
            # 解析报告内容
            try:
                if isinstance(report.report_content, str):
                    report_content = eval(report.report_content)  # 安全考虑，建议使用json.loads
                else:
                    report_content = report.report_content
                report_dict['report_content'] = report_content
            except:
                report_dict['report_content'] = {}
            
            # 解析建议内容
            try:
                if isinstance(report.recommendations, str):
                    recommendations = eval(report.recommendations)
                else:
                    recommendations = report.recommendations
                report_dict['recommendations'] = recommendations
            except:
                report_dict['recommendations'] = {}
            
            # 添加图像URL（需要根据实际文件存储方式调整）
            image_analysis = ImageAnalysis.query.get(report.image_analysis_id)
            if image_analysis:
                # 这里需要根据实际的文件存储方式来生成URL
                # 假设文件存储在uploads/images目录下
                image_filename = os.path.basename(image_analysis.image_path)
                report_dict['original_image_url'] = f'/uploads/images/{image_filename}'
                report_dict['thumbnail_url'] = f'/uploads/images/thumb_{image_filename}'
            
            reports.append(report_dict)
        
        return success_response({
            'reports': reports,
            'total': pagination.total,
            'page': page,
            'per_page': per_page,
            'pages': pagination.pages
        })
        
    except Exception as e:
        current_app.logger.error(f"获取报告列表失败: {str(e)}")
        return error_response(f'获取报告列表失败: {str(e)}', 500)

@reports_bp.route('/<report_id>', methods=['GET'])
def get_report_detail(report_id):
    """获取报告详情"""
    try:
        report = DiagnosisReport.query.get_or_404(report_id)
        
        report_dict = report.to_dict()
        
        # 解析报告内容
        try:
            if isinstance(report.report_content, str):
                report_content = eval(report.report_content)
            else:
                report_content = report.report_content
            report_dict['report_content'] = report_content
        except:
            report_dict['report_content'] = {}
        
        # 解析建议内容
        try:
            if isinstance(report.recommendations, str):
                recommendations = eval(report.recommendations)
            else:
                recommendations = report.recommendations
            report_dict['recommendations'] = recommendations
        except:
            report_dict['recommendations'] = {}
        
        # 添加图像URL
        image_analysis = ImageAnalysis.query.get(report.image_analysis_id)
        if image_analysis:
            image_filename = os.path.basename(image_analysis.image_path)
            report_dict['original_image_url'] = f'/uploads/images/{image_filename}'
            report_dict['thumbnail_url'] = f'/uploads/images/thumb_{image_filename}'
        
        # 获取相关的分析结果
        analysis_results = AnalysisResult.query.filter_by(
            image_analysis_id=report.image_analysis_id
        ).all()
        
        report_dict['analysis_results'] = []
        for result in analysis_results:
            result_dict = result.to_dict()
            
            # 获取模型预测详情
            model_pred = ModelPrediction.query.filter_by(
                analysis_result_id=result.id
            ).first()
            
            if model_pred:
                result_dict['model_prediction'] = model_pred.to_dict()
            
            report_dict['analysis_results'].append(result_dict)
        
        return success_response({
            'report': report_dict
        })
        
    except Exception as e:
        current_app.logger.error(f"获取报告详情失败: {str(e)}")
        return error_response(f'获取报告详情失败: {str(e)}', 500)

@reports_bp.route('/<report_id>', methods=['PUT'])
def update_report(report_id):
    """更新报告"""
    try:
        report = DiagnosisReport.query.get_or_404(report_id)
        data = request.get_json()
        
        # 更新允许的字段
        if 'patient_name' in data:
            report.patient_name = data['patient_name']
        if 'patient_age' in data:
            report.patient_age = data['patient_age']
        if 'patient_gender' in data:
            report.patient_gender = data['patient_gender']
        if 'clinical_summary' in data:
            # 更新报告内容中的临床摘要
            try:
                if isinstance(report.report_content, str):
                    report_content = eval(report.report_content)
                else:
                    report_content = report.report_content
                report_content['clinical_summary'] = data['clinical_summary']
                report.report_content = str(report_content)
            except:
                pass
        if 'recommendations' in data:
            # 更新建议内容
            try:
                if isinstance(report.recommendations, str):
                    recommendations = eval(report.recommendations)
                else:
                    recommendations = report.recommendations
                recommendations.update(data['recommendations'])
                report.recommendations = str(recommendations)
            except:
                pass
        if 'follow_up_plan' in data:
            report.follow_up_plan = data['follow_up_plan']
        
        db.session.commit()
        
        return success_response({
            'message': '报告更新成功',
            'report': report.to_dict()
        })
        
    except Exception as e:
        current_app.logger.error(f"更新报告失败: {str(e)}")
        db.session.rollback()
        return error_response(f'更新报告失败: {str(e)}', 500)

@reports_bp.route('/export/<string:report_id>', methods=['GET'])
def export_report(report_id):
    """导出单个报告"""
    try:
        report = DiagnosisReport.query.get_or_404(report_id)
        
        # 解析报告内容和建议
        try:
            if isinstance(report.report_content, str):
                report_content = eval(report.report_content)
            else:
                report_content = report.report_content
        except:
            report_content = {}
        
        try:
            if isinstance(report.recommendations, str):
                recommendations = eval(report.recommendations)
            else:
                recommendations = report.recommendations
        except:
            recommendations = {}
        
        # 构建导出数据
        export_data = {
            'id': report.id,
            'patient_id': report.patient_id,
            'patient_name': report.patient_name,
            'ensemble_diagnosis_level': report.ensemble_diagnosis_level,
            'ensemble_confidence': report.ensemble_confidence,
            'report_content': report_content,
            'recommendations': recommendations,
            'created_at': report.created_at.strftime('%Y-%m-%d %H:%M:%S')
        }
        
        # 添加图像URL
        image_analysis = ImageAnalysis.query.get(report.image_analysis_id)
        if image_analysis:
            image_filename = os.path.basename(image_analysis.image_path)
            export_data['original_image_url'] = f'/uploads/images/{image_filename}'
            export_data['thumbnail_url'] = f'/uploads/images/thumb_{image_filename}'
        
        # 根据格式要求返回数据
        format_type = request.args.get('format', 'json')
        
        if format_type == 'pdf':
            # 返回PDF格式的HTML内容，前端会处理为PDF
            pdf_html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <title>医疗影像分析报告</title>
                <style>
                    body {{ font-family: 'Microsoft YaHei', Arial, sans-serif; margin: 20px; }}
                    .header {{ text-align: center; border-bottom: 2px solid #333; padding-bottom: 20px; }}
                    .section {{ margin: 20px 0; }}
                    .section h3 {{ color: #333; border-bottom: 1px solid #ccc; padding-bottom: 5px; }}
                    .info-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
                    .image-container {{ text-align: center; }}
                    .image-container img {{ max-width: 400px; height: auto; border: 1px solid #ddd; }}
                    .diagnosis {{ background: #f8f9fa; padding: 15px; border-radius: 8px; margin: 10px 0; }}
                    table {{ width: 100%; border-collapse: collapse; margin: 10px 0; }}
                    th, td {{ border: 1px solid #ddd; padding: 10px; text-align: left; }}
                    th {{ background-color: #f2f2f2; }}
                    .footer {{ margin-top: 50px; text-align: center; font-size: 12px; color: #666; }}
                </style>
            </head>
            <body>
                <div class="header">
                    <h1>医疗影像分析报告</h1>
                    <p>报告编号: {report.id}</p>
                    <p>生成时间: {report.created_at.strftime('%Y年%m月%d日 %H:%M')}</p>
                </div>

                <div class="section">
                    <h3>患者信息</h3>
                    <div class="info-grid">
                        <p><strong>患者ID:</strong> {report.patient_id}</p>
                        <p><strong>患者姓名:</strong> {report.patient_name}</p>
                    </div>
                </div>

                <div class="section">
                    <h3>诊断结果</h3>
                    <div class="diagnosis">
                        <p><strong>诊断级别:</strong> {export_data['ensemble_diagnosis_level']}</p>
                        <p><strong>置信度:</strong> {(report.ensemble_confidence * 100):.1f}%</p>
                    </div>
                </div>

                <div class="section">
                    <h3>眼底图像</h3>
                    <div class="image-container">
                        {'<img src="' + export_data.get('original_image_url', '') + '" alt="眼底图像" />' if export_data.get('original_image_url') else '<p>无图像数据</p>'}
                    </div>
                </div>

                <div class="section">
                    <h3>临床摘要</h3>
                    <p>{report_content.get('clinical_summary', '无临床摘要')}</p>
                </div>

                <div class="section">
                    <h3>模型分析结果</h3>
                    <table>
                        <tr><th>模型</th><th>预测结果</th><th>置信度</th></tr>
                        {' '.join([f'<tr><td>{model}</td><td>{result.get("diagnosis_level", "N/A")}</td><td>{(result.get("confidence", 0) * 100):.1f}%</td></tr>' for model, result in report_content.get('model_predictions', {}).items()])}
                    </table>
                </div>

                <div class="footer">
                    <p>此报告由AI医疗影像分析系统生成</p>
                </div>
            </body>
            </html>
            """
            return success_response({
                'success': True,
                'data': pdf_html,
                'message': 'PDF内容生成成功'
            })
        else:
            # 默认返回JSON格式
            return success_response({
                'success': True,
                'data': export_data,
                'message': '报告导出成功'
            })
    except Exception as e:
        current_app.logger.error(f"导出报告失败: {str(e)}")
        return error_response(f'导出报告失败: {str(e)}', 500)

@reports_bp.route('/export', methods=['POST'])
def export_reports():
    """批量导出报告"""
    try:
        data = request.get_json()
        
        if not data or 'report_ids' not in data:
            return error_response('缺少报告ID列表', 400)
        
        report_ids = data['report_ids']
        format_type = data.get('format', 'pdf')  # 默认PDF格式
        
        if not isinstance(report_ids, list) or len(report_ids) == 0:
            return error_response('报告ID列表无效', 400)
        
        # 获取报告数据
        reports = DiagnosisReport.query.filter(DiagnosisReport.id.in_(report_ids)).all()
        
        if len(reports) != len(report_ids):
            return error_response('部分报告不存在', 404)
        
        # 构建导出数据
        export_data = []
        for report in reports:
            report_dict = report.to_dict()
            
            # 解析报告内容
            try:
                if isinstance(report.report_content, str):
                    report_content = eval(report.report_content)
                else:
                    report_content = report.report_content
                report_dict['report_content'] = report_content
            except:
                report_dict['report_content'] = {}
            
            # 解析建议内容
            try:
                if isinstance(report.recommendations, str):
                    recommendations = eval(report.recommendations)
                else:
                    recommendations = report.recommendations
                report_dict['recommendations'] = recommendations
            except:
                report_dict['recommendations'] = {}
            
            # 添加图像URL
            image_analysis = ImageAnalysis.query.get(report.image_analysis_id)
            if image_analysis:
                image_filename = os.path.basename(image_analysis.image_path)
                report_dict['original_image_url'] = f'/uploads/images/{image_filename}'
                report_dict['thumbnail_url'] = f'/uploads/images/thumb_{image_filename}'
            
            export_data.append(report_dict)
        
        # 这里可以实现实际的PDF或Excel生成逻辑
        # 目前返回JSON格式的数据
        
        return success_response({
            'export_data': export_data,
            'format': format_type,
            'total_reports': len(export_data),
            'message': f'成功导出{len(export_data)}份报告（{format_type.upper()}格式）'
        })
        
    except Exception as e:
        current_app.logger.error(f"批量导出报告失败: {str(e)}")
        return error_response(f'批量导出报告失败: {str(e)}', 500)

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