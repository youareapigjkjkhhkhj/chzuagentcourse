#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
图像分析相关数据库模型
"""

import uuid
from datetime import datetime
from .base import db

class ImageAnalysis(db.Model):
    """图像分析记录表"""
    __tablename__ = 'image_analysis'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    image_filename = db.Column(db.String(255), nullable=False, comment='图像文件名')
    image_path = db.Column(db.String(500), nullable=False, comment='图像文件存储路径')
    image_hash = db.Column(db.String(64), nullable=False, unique=True, comment='图像文件哈希值(SHA-256)')
    image_size = db.Column(db.Integer, nullable=False, comment='图像文件大小(字节)')
    image_format = db.Column(db.String(10), nullable=False, comment='图像格式类型，如JPG、PNG等')
    analysis_status = db.Column(db.String(20), default='pending', comment='分析状态：pending、processing、completed、failed')
    created_at = db.Column(db.DateTime, default=datetime.utcnow, comment='创建时间')
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment='更新时间')
    
    # 关联关系
    analysis_results = db.relationship('AnalysisResult', backref='image_analysis', lazy=True, cascade='all, delete-orphan')
    diagnosis_reports = db.relationship('DiagnosisReport', backref='image_analysis', lazy=True)
    
    def to_dict(self):
        """转换为字典格式"""
        return {
            'id': self.id,
            'image_filename': self.image_filename,
            'image_path': self.image_path,
            'image_hash': self.image_hash,
            'image_size': self.image_size,
            'image_format': self.image_format,
            'analysis_status': self.analysis_status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

class AnalysisResult(db.Model):
    """分析结果表"""
    __tablename__ = 'analysis_results'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    image_analysis_id = db.Column(db.String(36), db.ForeignKey('image_analysis.id'), nullable=False, comment='关联图像分析记录ID')
    model_name = db.Column(db.String(100), nullable=False, comment='使用的模型名称')
    prediction_level = db.Column(db.Integer, nullable=False, comment='预测的诊断级别 (0-4)')
    confidence_score = db.Column(db.Float, nullable=False, comment='置信度分数 (0-1)')
    processing_time = db.Column(db.Float, comment='处理时间(秒)')
    image_quality = db.Column(db.String(20), comment='图像质量：good、fair、poor')
    features_extracted = db.Column(db.Text, comment='提取的特征描述')
    created_at = db.Column(db.DateTime, default=datetime.utcnow, comment='创建时间')
    
    def to_dict(self):
        """转换为字典格式"""
        return {
            'id': self.id,
            'image_analysis_id': self.image_analysis_id,
            'model_name': self.model_name,
            'prediction_level': self.prediction_level,
            'confidence_score': self.confidence_score,
            'processing_time': self.processing_time,
            'image_quality': self.image_quality,
            'features_extracted': self.features_extracted,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

class ModelPrediction(db.Model):
    """模型预测详细结果表"""
    __tablename__ = 'model_predictions'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    analysis_result_id = db.Column(db.String(36), db.ForeignKey('analysis_results.id'), nullable=False, comment='关联分析结果ID')
    class_0_prob = db.Column(db.Float, comment='类别0概率(无糖尿病视网膜病变)')
    class_1_prob = db.Column(db.Float, comment='类别1概率(轻度非增殖性)')
    class_2_prob = db.Column(db.Float, comment='类别2概率(中度非增殖性)')
    class_3_prob = db.Column(db.Float, comment='类别3概率(重度非增殖性)')
    class_4_prob = db.Column(db.Float, comment='类别4概率(增殖性)')
    raw_prediction = db.Column(db.Text, comment='模型原始预测输出')
    created_at = db.Column(db.DateTime, default=datetime.utcnow, comment='创建时间')
    
    def to_dict(self):
        """转换为字典格式"""
        return {
            'id': self.id,
            'analysis_result_id': self.analysis_result_id,
            'class_probabilities': {
                '0': self.class_0_prob,
                '1': self.class_1_prob,
                '2': self.class_2_prob,
                '3': self.class_3_prob,
                '4': self.class_4_prob
            },
            'raw_prediction': self.raw_prediction,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

class DiagnosisReport(db.Model):
    """诊断报告表"""
    __tablename__ = 'diagnosis_reports'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    image_analysis_id = db.Column(db.String(36), db.ForeignKey('image_analysis.id'), nullable=False, comment='关联图像分析记录ID')
    patient_id = db.Column(db.String(255), comment='患者ID')
    patient_name = db.Column(db.String(100), comment='患者姓名')
    patient_age = db.Column(db.Integer, comment='患者年龄')
    patient_gender = db.Column(db.String(10), comment='患者性别')
    ensemble_diagnosis_level = db.Column(db.Integer, nullable=False, comment='集成模型最终诊断级别 (0-4)')
    ensemble_confidence = db.Column(db.Float, nullable=False, comment='集成模型置信度')
    report_content = db.Column(db.Text, nullable=False, comment='报告内容JSON格式')
    recommendations = db.Column(db.Text, comment='建议内容JSON格式')
    risk_level = db.Column(db.String(20), comment='风险等级：low、medium、high、critical')
    follow_up_plan = db.Column(db.Text, comment='随访计划')
    created_at = db.Column(db.DateTime, default=datetime.utcnow, comment='创建时间')
    
    def to_dict(self):
        """转换为字典格式"""
        return {
            'id': self.id,
            'image_analysis_id': self.image_analysis_id,
            'patient_id': self.patient_id,
            'patient_name': self.patient_name,
            'patient_age': self.patient_age,
            'patient_gender': self.patient_gender,
            'ensemble_diagnosis_level': self.ensemble_diagnosis_level,
            'ensemble_confidence': self.ensemble_confidence,
            'report_content': self.report_content,
            'recommendations': self.recommendations,
            'risk_level': self.risk_level,
            'follow_up_plan': self.follow_up_plan,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }