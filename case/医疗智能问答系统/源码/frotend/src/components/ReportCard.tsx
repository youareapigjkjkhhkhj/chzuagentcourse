import { DiagnosisReport } from '../types';
import DiagnosisLevel from './DiagnosisLevel';
import { motion } from 'framer-motion';
import { useState, useRef, useEffect } from 'react';
import { toast } from 'sonner';
import { Card, Button, Dropdown, Avatar } from 'tdesign-react';
import { FileIcon, DownloadIcon, MoreIcon } from 'tdesign-icons-react';

interface ReportCardProps {
  report: DiagnosisReport;
  onClick: () => void;
  onExportPDF?: (report: DiagnosisReport) => void;
  onExportCSV?: (report: DiagnosisReport) => void;
}

export default function ReportCard({ report, onClick, onExportPDF, onExportCSV }: ReportCardProps) {
  // 格式化日期
  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    return date.toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  // 导出菜单状态
  const [showExportMenu, setShowExportMenu] = useState(false);
  const exportMenuRef = useRef<HTMLDivElement>(null);

  // 点击外部关闭导出菜单
  const handleClickOutside = (event: MouseEvent) => {
    if (exportMenuRef.current && !exportMenuRef.current.contains(event.target as Node)) {
      setShowExportMenu(false);
    }
  };

  // 添加事件监听器
  useEffect(() => {
    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, []);

  // 处理导出按钮点击，阻止事件冒泡
  const handleExportClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    setShowExportMenu(!showExportMenu);
  };

  // 处理PDF导出
  const handlePDFExport = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (onExportPDF) {
      onExportPDF(report);
    }
    setShowExportMenu(false);
  };

  // 处理CSV导出
  const handleCSVExport = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (onExportCSV) {
      onExportCSV(report);
    }
    setShowExportMenu(false);
  };

  return (
    <Card
      hover
      onClick={onClick}
      style={{ cursor: 'pointer' }}
      cover={
        <div style={{ height: 120, overflow: 'hidden' }}>
          <img 
            src={report.imageUrl} 
            alt="眼底图像" 
            style={{ width: '100%', height: '100%', objectFit: 'cover' }}
          />
        </div>
      }
      actions={[
        onExportPDF && (
          <Button key="pdf" theme="default" variant="text" onClick={handlePDFExport} prefixIcon={<FileIcon />}>
            PDF
          </Button>
        ),
        onExportCSV && (
          <Button key="csv" theme="default" variant="text" onClick={handleCSVExport} prefixIcon={<DownloadIcon />}>
            CSV
          </Button>
        )
      ].filter(Boolean)}
    >
      <div style={{ marginBottom: 8 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div>
            <h3 style={{ fontWeight: 600, fontSize: 16, marginBottom: 4 }}>
              患者ID: {report.patientId}
            </h3>
            {report.patientName && (
              <p style={{ color: '#666' }}>{report.patientName}</p>
            )}
          </div>
          <DiagnosisLevel level={report.finalDiagnosis} size="small" />
        </div>
      </div>
      
      <p style={{ fontSize: 14, color: '#666', marginBottom: 12, lineHeight: 1.5 }}>
        {report.clinicalSummary}
      </p>
      
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: '#999' }}>
        <span>{formatDate(report.createdAt)}</span>
        <span>{report.analysisResults.length} 个模型分析</span>
      </div>
    </Card>
  );
}