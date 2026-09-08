import { useContext, useState } from 'react';
import { AuthContext } from '../contexts/authContext';
import Navbar from '../components/Navbar';
import Sidebar from '../components/Sidebar';
import { motion } from 'framer-motion';
import { toast } from 'sonner';
import { DiagnosisLevel as DiagnosisLevelType } from '../types';

export default function SystemSettings() {
  const { user } = useContext(AuthContext);
  
  // 诊断阈值设置
  const [diagnosisThresholds, setDiagnosisThresholds] = useState({
    NoDR: 0.5,
    Mild: 0.6,
    Moderate: 0.7,
    Severe: 0.8,
    Proliferative: 0.9
  });
  
  // 通知设置
  const [notificationSettings, setNotificationSettings] = useState({
    emailEnabled: true,
    pushEnabled: false,
    highRiskOnly: true
  });
  
  // 存储设置
  const [storageSettings, setStorageSettings] = useState({
    autoBackup: true,
    retentionPeriod: 365 // 天
  });
  
  // 标签页状态
  const [activeTab, setActiveTab] = useState<'diagnosis' | 'notification' | 'storage' | 'about'>('diagnosis');

  const handleThresholdChange = (level: DiagnosisLevelType, value: number) => {
    setDiagnosisThresholds(prev => ({
      ...prev,
      [level]: value
    }));
  };

  const handleNotificationChange = (key: keyof typeof notificationSettings, value: boolean) => {
    setNotificationSettings(prev => ({
      ...prev,
      [key]: value
    }));
  };

  const handleStorageChange = (key: keyof typeof storageSettings, value: any) => {
    setStorageSettings(prev => ({
      ...prev,
      [key]: value
    }));
  };

  const handleSaveSettings = () => {
    // 在实际应用中，这里应该保存设置到后端或LocalStorage
    toast.success('设置已保存');
  };

  const handleRestoreDefaults = () => {
    if (window.confirm('确定要恢复默认设置吗？当前设置将被覆盖。')) {
      setDiagnosisThresholds({
        NoDR: 0.5,
        Mild: 0.6,
        Moderate: 0.7,
        Severe: 0.8,
        Proliferative: 0.9
      });
      
      setNotificationSettings({
        emailEnabled: true,
        pushEnabled: false,
        highRiskOnly: true
      });
      
      setStorageSettings({
        autoBackup: true,
        retentionPeriod: 365
      });
      
      toast.success('已恢复默认设置');
    }
  };

  const handleBackupData = () => {
    toast.info('数据备份功能即将上线');
  };

  const handleCleanupData = () => {
    if (window.confirm('确定要清理旧数据吗？此操作无法撤销。')) {
      toast.success('数据清理功能即将上线');
    }
  };

  return (
    <div className="bg-gray-50 min-h-screen flex flex-col">
      <Navbar />
      <div className="flex flex-1">
        <Sidebar />
        <main className="flex-1 ml-64 p-6">
          <div className="max-w-4xl mx-auto">
            <motion.header 
              initial={{ opacity: 0, y: -20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5 }}
              className="mb-8"
            >
              <h1 className="text-2xl font-bold text-gray-900">系统设置</h1>
              <p className="text-gray-600 mt-1">配置系统参数和偏好设置</p>
            </motion.header>
            
            {/* 设置标签页导航 */}
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, delay: 0.1 }}
              className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden mb-6"
            >
              <div className="flex border-b border-gray-200">
                <button
                  className={`px-6 py-3 text-sm font-medium transition-colors ${
                    activeTab === 'diagnosis' 
                      ? 'border-b-2 border-blue-600 text-blue-600' 
                      : 'text-gray-500 hover:text-gray-700'
                  }`}
                  onClick={() => setActiveTab('diagnosis')}
                >
                  诊断阈值
                </button>
                <button
                  className={`px-6 py-3 text-sm font-medium transition-colors ${
                    activeTab === 'notification' 
                      ? 'border-b-2 border-blue-600 text-blue-600' 
                      : 'text-gray-500 hover:text-gray-700'
                  }`}
                  onClick={() => setActiveTab('notification')}
                >
                  通知设置
                </button>
                <button
                  className={`px-6 py-3 text-sm font-medium transition-colors ${
                    activeTab === 'storage' 
                      ? 'border-b-2 border-blue-600 text-blue-600' 
                      : 'text-gray-500 hover:text-gray-700'
                  }`}
                  onClick={() => setActiveTab('storage')}
                >
                  存储设置
                </button>
                <button
                  className={`px-6 py-3 text-sm font-medium transition-colors ${
                    activeTab === 'about' 
                      ? 'border-b-2 border-blue-600 text-blue-600' 
                      : 'text-gray-500 hover:text-gray-700'
                  }`}
                  onClick={() => setActiveTab('about')}
                >
                  关于系统
                </button>
              </div>
            </motion.div>
            
            {/* 设置内容 */}
            <motion.div
              key={activeTab}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.3 }}
              className="bg-white rounded-xl shadow-sm p-6 border border-gray-200 mb-6"
            >
              {/* 诊断阈值设置 */}
              {activeTab === 'diagnosis' && (
                <div className="space-y-6">
                  <div>
                    <h3 className="text-lg font-semibold text-gray-900 mb-4">诊断阈值设置</h3>
                    <p className="text-sm text-gray-500 mb-6">
                      调整各诊断级别的置信度阈值。当AI模型的置信度超过阈值时，将使用该诊断级别。
                    </p>
                    
                    <div className="space-y-6">
                      {Object.entries(diagnosisThresholds).map(([level, threshold]) => (
                        <div key={level}>
                          <div className="flex justify-between items-center mb-2">
                            <label 
                              htmlFor={`threshold-${level}`} 
                              className="block text-sm font-medium text-gray-700"
                            >
                              {level === 'NoDR' && '无明显视网膜病变'}
                              {level === 'Mild' && '轻度非增殖性'}
                              {level === 'Moderate' && '中度非增殖性'}
                              {level === 'Severe' && '重度非增殖性'}
                              {level === 'Proliferative' && '增殖性'}
                            </label>
                            <span className="text-sm text-gray-500">
                              {(threshold * 100).toFixed(0)}%
                            </span>
                          </div>
                          <input
                            type="range"
                            id={`threshold-${level}`}
                            min="0.1"
                            max="0.99"
                            step="0.01"
                            value={threshold}
                            onChange={(e) => handleThresholdChange(level as DiagnosisLevelType, parseFloat(e.target.value))}
                            className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer"
                          />
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              )}
              
              {/* 通知设置 */}
              {activeTab === 'notification' && (
                <div className="space-y-6">
                  <div>
                    <h3 className="text-lg font-semibold text-gray-900 mb-4">通知设置</h3>
                    <p className="text-sm text-gray-500 mb-6">
                      配置系统通知偏好，包括邮件通知和推送通知。
                    </p>
                    
                    <div className="space-y-4">
                      <div className="flex items-center justify-between p-4 border rounded-lg hover:bg-gray-50 transition-colors">
                        <div>
                          <h4 className="font-medium text-gray-900">启用邮件通知</h4>
                          <p className="text-sm text-gray-500">接收重要系统通知和报告提醒</p>
                        </div>
                        <label className="relative inline-flex items-center cursor-pointer">
                          <input
                            type="checkbox"
                            checked={notificationSettings.emailEnabled}
                            onChange={(e) => handleNotificationChange('emailEnabled', e.target.checked)}
                            className="sr-only peer"
                          />
                          <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-blue-300 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
                        </label>
                      </div>
                      
                      <div className="flex items-center justify-between p-4 border rounded-lg hover:bg-gray-50 transition-colors">
                        <div>
                          <h4 className="font-medium text-gray-900">启用推送通知</h4>
                          <p className="text-sm text-gray-500">通过浏览器接收实时通知</p>
                        </div>
                        <label className="relative inline-flex items-center cursor-pointer">
                          <input
                            type="checkbox"
                            checked={notificationSettings.pushEnabled}
                            onChange={(e) => handleNotificationChange('pushEnabled', e.target.checked)}
                            className="sr-only peer"
                          />
                          <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-blue-300 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
                        </label>
                      </div>
                      
                      <div className="flex items-center justify-between p-4 border rounded-lg hover:bg-gray-50 transition-colors">
                        <div>
                          <h4 className="font-medium text-gray-900">仅高风险病例通知</h4>
                          <p className="text-sm text-gray-500">仅接收重度和增殖性病变的通知</p>
                        </div>
                        <label className="relative inline-flex items-center cursor-pointer">
                          <input
                            type="checkbox"
                            checked={notificationSettings.highRiskOnly}
                            onChange={(e) => handleNotificationChange('highRiskOnly', e.target.checked)}
                            className="sr-only peer"
                          />
                          <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-blue-300 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
                        </label>
                      </div>
                    </div>
                  </div>
                </div>
              )}
              
              {/* 存储设置 */}
              {activeTab === 'storage' && (
                <div className="space-y-6">
                  <div>
                    <h3 className="text-lg font-semibold text-gray-900 mb-4">存储设置</h3>
                    <p className="text-sm text-gray-500 mb-6">
                      配置数据存储和备份偏好。
                    </p>
                    
                    <div className="space-y-4 mb-6">
                      <div className="flex items-center justify-between p-4 border rounded-lg hover:bg-gray-50 transition-colors">
                        <div>
                          <h4 className="font-medium text-gray-900">自动备份</h4>
                          <p className="text-sm text-gray-500">定期自动备份系统数据</p>
                        </div>
                        <label className="relative inline-flex items-center cursor-pointer">
                          <input
                            type="checkbox"
                            checked={storageSettings.autoBackup}
                            onChange={(e) => handleStorageChange('autoBackup', e.target.checked)}
                            className="sr-only peer"
                          />
                          <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-blue-300 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
                        </label>
                      </div>
                      
                      <div className="p-4 border rounded-lg hover:bg-gray-50 transition-colors">
                        <div className="flex justify-between items-center mb-2">
                          <div>
                            <h4 className="font-medium text-gray-900">数据保留期限</h4>
                            <p className="text-sm text-gray-500">自动清理超过保留期限的历史数据</p>
                          </div>
                          <span className="text-sm font-medium text-gray-900">
                            {storageSettings.retentionPeriod} 天
                          </span>
                        </div>
                        <input
                          type="range"
                          min="30"
                          max="730"
                          step="30"
                          value={storageSettings.retentionPeriod}
                          onChange={(e) => handleStorageChange('retentionPeriod', parseInt(e.target.value))}
                          className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer"
                        />
                        <div className="flex justify-between text-xs text-gray-500 mt-1">
                          <span>30天</span>
                          <span>730天</span>
                        </div>
                      </div>
                    </div>
                    
                    <div className="border-t border-gray-200 pt-6">
                      <h4 className="font-medium text-gray-900 mb-4">数据管理</h4>
                      <div className="flex flex-col sm:flex-row space-y-3 sm:space-y-0 sm:space-x-3">
                        <motion.button
                          whileHover={{ scale: 1.02 }}
                          whileTap={{ scale: 0.98 }}
                          onClick={handleBackupData}
                          className="px-4 py-2 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 transition-colors flex items-center justify-center"
                        >
                          <i className="fas fa-database mr-2"></i>
                          手动备份数据
                        </motion.button>
                        <motion.button
                          whileHover={{ scale: 1.02 }}
                          whileTap={{ scale: 0.98 }}
                          onClick={handleCleanupData}
                          className="px-4 py-2 bg-red-600 text-white rounded-lg font-medium hover:bg-red-700 transition-colors flex items-center justify-center"
                        >
                          <i className="fas fa-broom mr-2"></i>
                          清理旧数据
                        </motion.button>
                      </div>
                    </div>
                  </div>
                </div>
              )}
              
              {/* 关于系统 */}
              {activeTab === 'about' && (
                <div className="space-y-6">
                  <div className="flex flex-col items-center text-center">
                    <div className="w-20 h-20 bg-blue-100 rounded-full flex items-center justify-center mb-4">
                      <i className="fas fa-heartbeat text-blue-600 text-3xl"></i>
                    </div>
                    <h3 className="text-xl font-bold text-gray-900">AI糖尿病辅助诊断系统</h3>
                    <p className="text-sm text-gray-500 mt-2">版本 1.0.0</p>
                    
                    <div className="mt-8 space-y-4 w-full max-w-md">
                      <div className="p-4 border rounded-lg bg-gray-50">
                        <h4 className="font-medium text-gray-900 mb-2">系统信息</h4>
                        <div className="grid grid-cols-2 gap-2 text-sm">
                          <div className="text-gray-500">开发团队</div>
                          <div className="text-gray-900">医疗AI研究团队</div>
                          <div className="text-gray-500">发布日期</div>
                          <div className="text-gray-900">2025年11月</div>
                          <div className="text-gray-500">技术栈</div>
                          <div className="text-gray-900">React + TypeScript</div>
                          <div className="text-gray-500">AI模型</div>
                          <div className="text-gray-900">ResNet, DenseNet, EfficientNet</div>
                        </div>
                      </div>
                      
                      <div className="p-4 border rounded-lg bg-blue-50">
                        <h4 className="font-medium text-blue-800 mb-2">关于本系统</h4>
                        <p className="text-sm text-blue-700">
                          AI糖尿病辅助诊断系统是一个基于人工智能的医疗应用，通过分析眼底图像，辅助医生诊断糖尿病视网膜病变(DR)。本系统使用深度学习模型对眼底图像进行分析，提供准确的诊断建议。
                        </p>
                      </div>
                      
                      <div className="p-4 border rounded-lg">
                        <h4 className="font-medium text-gray-900 mb-2">联系方式</h4>
                        <p className="text-sm text-gray-600 mb-2">
                          <i className="fas fa-envelope mr-2 text-gray-500"></i>
                          support@aidr-system.com
                        </p>
                        <p className="text-sm text-gray-600">
                          <i className="fas fa-phone mr-2 text-gray-500"></i>
                          400-123-4567
                        </p>
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </motion.div>
            
            {/* 底部操作按钮 */}
            {activeTab !== 'about' && (
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5, delay: 0.2 }}
                className="flex justify-end space-x-3"
              >
                <motion.button
                  whileHover={{ scale: 1.05 }}
                  whileTap={{ scale: 0.95 }}
                  onClick={handleRestoreDefaults}
                  className="px-4 py-2 border border-gray-300 rounded-lg font-medium text-gray-700 hover:bg-gray-50 transition-colors"
                >
                  恢复默认设置
                </motion.button>
                <motion.button
                  whileHover={{ scale: 1.05 }}
                  whileTap={{ scale: 0.95 }}
                  onClick={handleSaveSettings}
                  className="px-4 py-2 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 transition-colors"
                >
                  保存设置
                </motion.button>
              </motion.div>
            )}
          </div>
        </main>
      </div>
    </div>
  );
}