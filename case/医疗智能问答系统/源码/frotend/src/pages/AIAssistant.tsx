import { useState, useRef, useEffect } from 'react';
import { useContext } from 'react';
import { AuthContext } from '../contexts/authContext';
import { useModel } from '../contexts/modelContext';
import { useKnowledgeBase } from '../contexts/knowledgeBaseContext';
import { chatAPI, chatHistoryAPI } from '../services/api';
import Navbar from '../components/Navbar';
import Sidebar from '../components/Sidebar';
import { motion, AnimatePresence } from 'framer-motion';
import { toast } from 'sonner';

// 消息类型定义
interface Message {
  id: string;
  content: string;
  type: 'user' | 'ai';
  timestamp: Date;
  messageType?: 'report' | 'followup' | 'explain' | 'similar' | 'prompt' | 'normal';
  fromKnowledgeBase?: boolean;
  source?: string;
  sources?: Array<{
    id: string;
    title: string;
    content: string;
    score: number;
  }>;
}

// 病例信息接口
interface CaseInfo {
  patientId: string;
  age: number;
  gender: string;
  diabetesDuration: number;
  diagnosisLevel: string;
  symptoms: string[];
}

// 模拟病例数据
const mockCases: CaseInfo[] = [
  {
    patientId: 'P001',
    age: 45,
    gender: '男',
    diabetesDuration: 5,
    diagnosisLevel: 'Mild',
    symptoms: ['视力模糊', '眼前漂浮物']
  },
  {
    patientId: 'P002',
    age: 62,
    gender: '女',
    diabetesDuration: 12,
    diagnosisLevel: 'Moderate',
    symptoms: ['视力下降', '视野缺损']
  }
];

// 模拟生成诊断报告
const generateDiagnosisReport = (caseInfo?: Partial<CaseInfo>): string => {
  const defaultCase = {
    patientId: '未知',
    age: 50,
    gender: '未知',
    diabetesDuration: 5,
    diagnosisLevel: 'Mild',
    symptoms: []
  };
  
  const info = { ...defaultCase, ...caseInfo };
  
  return `
患者信息：
- 患者ID: ${info.patientId}
- 年龄: ${info.age}岁
- 性别: ${info.gender}
- 糖尿病病程: ${info.diabetesDuration}年

眼底图像分析结果：
- 图像质量评估：良好
- 视网膜血管可见度：清晰
- 微血管瘤：${info.diagnosisLevel === 'NoDR' ? '未发现' : '少量可见'}
- 出血点：${info.diagnosisLevel === 'NoDR' || info.diagnosisLevel === 'Mild' ? '未发现' : '少量可见'}
- 硬性渗出：${info.diagnosisLevel === 'NoDR' || info.diagnosisLevel === 'Mild' ? '未发现' : '少量可见'}
- 软性渗出：${info.diagnosisLevel === 'Severe' || info.diagnosisLevel === 'Proliferative' ? '可见' : '未发现'}
- 新生血管：${info.diagnosisLevel === 'Proliferative' ? '可见' : '未发现'}

AI诊断结论：
${info.diagnosisLevel} (${getDiagnosisLevelChinese(info.diagnosisLevel)})

置信度：${Math.floor(Math.random() * 20) + 80}%

建议：
${getRecommendations(info.diagnosisLevel)}
  `.trim();
};

// 获取诊断级别中文名称
const getDiagnosisLevelChinese = (level: string): string => {
  const levelMap: Record<string, string> = {
    'NoDR': '无明显视网膜病变',
    'Mild': '轻度非增殖性糖尿病视网膜病变',
    'Moderate': '中度非增殖性糖尿病视网膜病变',
    'Severe': '重度非增殖性糖尿病视网膜病变',
    'Proliferative': '增殖性糖尿病视网膜病变'
  };
  
  return levelMap[level] || '未知';
};

// 获取建议
const getRecommendations = (level: string): string => {
  const recommendations: Record<string, string> = {
    'NoDR': '继续保持良好的血糖控制，每年进行一次眼底检查。',
    'Mild': '建议每6个月进行一次眼底检查，加强血糖和血压控制。',
    'Moderate': '建议每3-4个月进行一次眼底检查，考虑转诊至眼科专科医生。',
    'Severe': '建议立即转诊至眼科专科医生，可能需要激光治疗。',
    'Proliferative': '需要立即进行眼科专科治疗，可能需要抗VEGF药物注射或激光治疗。'
  };
  
  return recommendations[level] || '请咨询专业医生获取详细建议。';
};

// 生成随访建议
const generateFollowUpRecommendations = (caseInfo?: Partial<CaseInfo>): string => {
  const defaultCase = {
    age: 50,
    diabetesDuration: 5,
    diagnosisLevel: 'Mild'
  };
  
  const info = { ...defaultCase, ...caseInfo };
  
  let followUpInterval = '每年一次';
  if (info.diagnosisLevel === 'Mild') followUpInterval = '每6个月一次';
  else if (info.diagnosisLevel === 'Moderate') followUpInterval = '每3-4个月一次';
  else if (info.diagnosisLevel === 'Severe' || info.diagnosisLevel === 'Proliferative') followUpInterval = '每1-2个月一次';
  
  return `
随访计划：
- 复查频率：${followUpInterval}
- 检查项目：眼底彩照、视力检查、眼压测量

生活方式建议：
- 控制血糖：空腹血糖控制在4.4-7.0 mmol/L，餐后2小时血糖<10.0 mmol/L
- 控制血压：血压控制在130/80 mmHg以下
- 控制血脂：LDL胆固醇控制在2.6 mmol/L以下
- 戒烟限酒：避免吸烟，限制酒精摄入
- 适量运动：每周至少150分钟中等强度有氧运动
- 健康饮食：低盐、低脂、高纤维饮食

注意事项：
${info.diagnosisLevel === 'Severe' || info.diagnosisLevel === 'Proliferative' ? 
  '- 病情较为严重，请密切遵循眼科医生的治疗建议\n- 如出现视力突然下降、眼前黑影增多的症状，请立即就医' : 
  '- 定期监测血糖、血压和血脂\n- 如出现视力变化，请及时就医'}
  `.trim();
};

// 生成术语解释
const generateTermExplanation = (term: string): string => {
  const explanations: Record<string, string> = {
    '糖尿病视网膜病变': '糖尿病视网膜病变（Diabetic Retinopathy, DR）是糖尿病最常见的微血管并发症之一，是由于长期高血糖导致视网膜血管损伤，引起视力下降甚至失明的一种眼部疾病。',
    
    '微血管瘤': '微血管瘤是糖尿病视网膜病变的早期表现，表现为视网膜毛细血管局部扩张形成的微小红色点状病变，通常不会直接影响视力，但提示视网膜血管已经受损。',
    
    '硬性渗出': '硬性渗出是糖尿病视网膜病变的表现之一，是由于视网膜血管渗漏导致的脂质沉积，呈现为黄色蜡样斑点，多位于视网膜外层，严重时可影响视力。',
    
    '软性渗出': '软性渗出triangleq棉絮斑，是糖尿病视网膜病变加重的表现，是由于视网膜缺血导致神经纤维层肿胀形成的白色絮状病变，提示视网膜血液循环严重受损。',
    
    '新生血管': '新生血管是增殖性糖尿病视网膜病变的特征性表现，是由于视网膜缺血缺氧刺激产生的新生异常血管，这些血管脆弱易出血，可导致玻璃体积血和视网膜脱离，严重威胁视力。',
    
    '黄斑水肿': '黄斑水肿是糖尿病视网膜病变导致视力下降的常见原因，是由于黄斑区视网膜血管渗漏导致液体积聚，引起中心视力下降、视物变形症状。'
  };
  
  return explanations[term] || `抱歉，我暂时没有关于"${term}"的详细解释。您可以尝试询问其他术语，或者咨询专业医生获取更准确的信息。`;
};

// 查找相似病例
const findSimilarCases = (caseInfo?: Partial<CaseInfo>): string => {
  const defaultCase = {
    diagnosisLevel: 'Mild',
    age: 50
  };
  
  const info = { ...defaultCase, ...caseInfo };
  
  // 模拟查找相似病例
  const similarCases = mockCases.filter(c => 
    c.diagnosisLevel === info.diagnosisLevel || 
    Math.abs(c.age - info.age!) <= 5
  ).slice(0, 2);
  
  if (similarCases.length === 0) {
    return '抱歉，暂时没有找到相似的病例数据。';
  }
  
  let result = `找到${similarCases.length}个相似病例：\n\n`;
  
  similarCases.forEach((caseItem, index) => {
    result += `病例${index + 1}：
- 患者ID: ${caseItem.patientId}
- 年龄: ${caseItem.age}岁
- 性别: ${caseItem.gender}
- 糖尿病病程: ${caseItem.diabetesDuration}年
- 诊断级别: ${getDiagnosisLevelChinese(caseItem.diagnosisLevel)}
- 症状: ${caseItem.symptoms.join('、')}

治疗方案：
${getTreatmentPlan(caseItem.diagnosisLevel)}

预后情况：
${getPrognosis(caseItem.diagnosisLevel)}

`;
  });
  
  return result.trim();
};

// 获取治疗方案
const getTreatmentPlan = (level: string): string => {
  const plans: Record<string, string> = {
    'NoDR': '观察，控制血糖、血压和血脂等危险因素。',
    'Mild': '药物治疗，严格控制血糖、血压和血脂，定期随访。',
    'Moderate': '药物治疗，可能需要激光光凝治疗，密切随访。',
    'Severe': '全视网膜激光光凝治疗，抗VEGF药物治疗，密切随访。',
    'Proliferative': '全视网膜激光光凝治疗，抗VEGF药物治疗，玻璃体切割手术（必要时），密切随访。'
  };
  
  return plans[level] || '请咨询专业医生获取详细治疗方案。';
};

// 获取预后情况
const getPrognosis = (level: string): string => {
  const prognoses: Record<string, string> = {
    'NoDR': '预后良好，保持良好的血糖控制和定期检查。',
    'Mild': '预后较好，需要严格控制危险因素和定期随访。',
    'Moderate': '预后中等，需要积极治疗和密切随访。',
    'Severe': '预后较差，需要及时治疗和密切随访。',
    'Proliferative': '预后差，需要积极治疗，有视力丧失风险。'
  };
  
  return prognoses[level] || '请咨询专业医生获取详细预后信息。';
};

export default function AIAssistant() {
  const { user } = useContext(AuthContext);
  const { models, loading: loadingModels, getDefaultModel } = useModel();
  const { knowledgeBases, loading: loadingKnowledgeBases, getDefaultKnowledgeBase } = useKnowledgeBase();
  
  // 获取默认模型和知识库
  const defaultModel = getDefaultModel();
  const defaultKnowledgeBase = getDefaultKnowledgeBase();
  
  const [messages, setMessages] = useState<Message[]>([
    {
      id: '1',
      content: '您好！我是AI医学助手，可以回答关于糖尿病视网膜病变的问题。您可以询问医学知识，也可以输入"生成报告"、"随访建议"、"解释术语"或"相似病例"获取更多AI辅助功能。',
      type: 'ai',
      timestamp: new Date(),
      messageType: 'normal'
    }
  ]);
  const [input, setInput] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [knowledgeBaseEnabled, setKnowledgeBaseEnabled] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [selectedModel, setSelectedModel] = useState(defaultModel?.id || '');
  const [selectedKnowledgeBase, setSelectedKnowledgeBase] = useState(defaultKnowledgeBase?.id || '');
  const [currentStreamCancel, setCurrentStreamCancel] = useState<(() => void) | null>(null);
  const [expandedSources, setExpandedSources] = useState<{ [key: string]: boolean }>({}); // 控制引用内容的展开/折叠
  const [chatSessions, setChatSessions] = useState<any[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [showSessionDialog, setShowSessionDialog] = useState(false);
  const [sessionTitle, setSessionTitle] = useState('');
  const [loadingSessions, setLoadingSessions] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // 当默认模型或知识库变化时，更新选中的值
  useEffect(() => {
    if (defaultModel && !selectedModel) {
      setSelectedModel(defaultModel.id);
    }
  }, [defaultModel, selectedModel]);
  
  useEffect(() => {
    if (defaultKnowledgeBase && !selectedKnowledgeBase) {
      setSelectedKnowledgeBase(defaultKnowledgeBase.id);
    }
  }, [defaultKnowledgeBase, selectedKnowledgeBase]);

  // 滚动到底部
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  // 切换引用内容的展开/折叠状态
  const toggleSourceExpansion = (messageId: string, sourceId: string) => {
    const key = `${messageId}_${sourceId}`;
    setExpandedSources(prev => ({
      ...prev,
      [key]: !prev[key]
    }));
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // 组件加载时加载会话列表
  useEffect(() => {
    if (user) {
      loadSessions();
    }
  }, [user]);

  // 组件卸载时取消流式请求
  useEffect(() => {
    return () => {
      if (currentStreamCancel) {
        currentStreamCancel();
      }
    };
  }, [currentStreamCancel]);

  // 加载会话列表
  const loadSessions = async () => {
    setLoadingSessions(true);
    try {
      const response = await chatHistoryAPI.getSessions();
      if (response.success) {
        setChatSessions(response.data);
      } else {
        toast.error('加载会话列表失败: ' + response.message);
      }
    } catch (error) {
      console.error('加载会话列表失败:', error);
      toast.error('加载会话列表失败');
    } finally {
      setLoadingSessions(false);
    }
  };

  // 加载会话消息
  const loadSessionMessages = async (sessionId: string) => {
    try {
      const response = await chatHistoryAPI.getMessages(sessionId);
      if (response.success) {
        const formattedMessages = response.data.map(msg => ({
          id: msg.id,
          content: msg.content,
          type: msg.role === 'user' ? 'user' : 'ai',
          timestamp: new Date(msg.created_at),
          fromKnowledgeBase: msg.metadata?.from_knowledge_base || false,
          sources: msg.metadata?.sources || []
        }));
        setMessages(formattedMessages);
        setCurrentSessionId(sessionId);
      } else {
        toast.error('加载会话消息失败: ' + response.message);
      }
    } catch (error) {
      console.error('加载会话消息失败:', error);
      toast.error('加载会话消息失败');
    }
  };

  // 创建新会话
  const createNewSession = async (title?: string) => {
    try {
      const sessionTitle = title || '新对话 ' + new Date().toLocaleString();
      const response = await chatHistoryAPI.createSession({
        title: sessionTitle,
        description: '',
        metadata: {
          model_id: selectedModel,
          knowledge_base_id: knowledgeBaseEnabled ? selectedKnowledgeBase : null
        }
      });
      
      if (response.success) {
        setCurrentSessionId(response.data.id);
        await loadSessions(); // 重新加载会话列表
        toast.success('新会话创建成功');
        return response.data.id;
      } else {
        toast.error('创建会话失败: ' + response.message);
        return null;
      }
    } catch (error) {
      console.error('创建会话失败:', error);
      toast.error('创建会话失败');
      return null;
    }
  };

  // 保存消息到会话
  const saveMessageToSession = async (sessionId: string, content: string, role: 'user' | 'assistant', metadata?: any) => {
    try {
      const response = await chatHistoryAPI.addMessage(sessionId, {
        content,
        role,
        metadata: metadata || {}
      });
      
      if (!response.success) {
        console.error('保存消息失败:', response.message);
      }
    } catch (error) {
      console.error('保存消息失败:', error);
    }
  };

  // 删除会话
  const deleteSession = async (sessionId: string) => {
    try {
      const response = await chatHistoryAPI.deleteSession(sessionId);
      
      if (response.success) {
        // 如果删除的是当前会话，清空消息并重置当前会话ID
        if (sessionId === currentSessionId) {
          setMessages([{
            id: '1',
            content: '您好！我是AI医学助手，可以回答关于糖尿病视网膜病变的问题。您可以询问医学知识，也可以输入"生成报告"、"随访建议"、"解释术语"或"相似病例"获取更多AI辅助功能。',
            type: 'ai',
            timestamp: new Date(),
            messageType: 'normal'
          }]);
          setCurrentSessionId(null);
        }
        
        // 重新加载会话列表
        await loadSessions();
        toast.success('会话删除成功');
      } else {
        toast.error('删除会话失败: ' + response.message);
      }
    } catch (error) {
      console.error('删除会话失败:', error);
      toast.error('删除会话失败');
    }
  };

  // 初始化时加载会话列表
  useEffect(() => {
    loadSessions();
  }, []);

  // 处理发送消息
  const handleSendMessage = async () => {
    if (!input.trim()) return;

    // 如果没有当前会话，创建一个新会话
    let sessionId = currentSessionId;
    if (!sessionId) {
      sessionId = await createNewSession();
      if (!sessionId) {
        toast.error('无法创建会话，请稍后再试');
        return;
      }
    }

    // 如果有正在进行的流式请求，先取消它
    if (currentStreamCancel) {
      currentStreamCancel();
      setCurrentStreamCancel(null);
    }

    const userMessage: Message = {
      id: Date.now().toString(),
      content: input,
      type: 'user',
      timestamp: new Date()
    };

    setMessages(prev => [...prev, userMessage]);
    
    // 保存用户消息到会话
    await saveMessageToSession(sessionId, input, 'user');
    
    setInput('');
    setIsTyping(true);

    // 创建一个空的AI消息，用于流式更新
    const aiMessageId = Date.now().toString() + '_ai';
    const aiMessage: Message = {
      id: aiMessageId,
      content: '',
      type: 'ai',
      timestamp: new Date(),
      fromKnowledgeBase: false, // 初始设置为false，在onEnd时更新
      sources: []
    };
    
    setMessages(prev => [...prev, aiMessage]);
    
    // 用于临时保存sources数据
    let savedSources: any[] = [];
    let finalResponse = '';

    try {
      // 使用流式聊天API
      const cancelStream = chatAPI.sendMessageStream({
        message: input,
        modelId: selectedModel,
        knowledgeBaseId: knowledgeBaseEnabled ? selectedKnowledgeBase : undefined,
        useKnowledgeBase: knowledgeBaseEnabled
      }, {
        onStart: (data) => {
          // 开始接收响应，保存源信息但不立即显示
          console.log('流式响应开始:', data); // 添加调试日志
          if (data.data) {
            // 临时保存sources数据
            savedSources = data.data.sources || [];
          }
        },
        onMessage: (content) => {
          // 流式更新消息内容
          finalResponse += content;
          setMessages(prev => prev.map(msg => 
            msg.id === aiMessageId 
              ? { ...msg, content: finalResponse }
              : msg
          ));
        },
        onEnd: () => {
          setIsTyping(false);
          setCurrentStreamCancel(null);
          // 在回答生成完成后，更新源信息和知识库标记
          setMessages(prev => prev.map(msg => 
            msg.id === aiMessageId 
              ? { 
                  ...msg, 
                  fromKnowledgeBase: knowledgeBaseEnabled,
                  sources: savedSources // 使用保存的sources数据
                }
              : msg
          ));
          
          // 保存AI响应到会话
          saveMessageToSession(sessionId, finalResponse, 'assistant', {
            from_knowledge_base: knowledgeBaseEnabled,
            sources: savedSources,
            model_id: selectedModel,
            knowledge_base_id: knowledgeBaseEnabled ? selectedKnowledgeBase : null
          });
        },
        onError: (error) => {
          console.error('流式聊天失败:', error);
          setIsTyping(false);
          setCurrentStreamCancel(null);
          // 如果流式请求失败，回退到普通请求
          handleFallbackMessage(input, userMessage.id, aiMessageId, sessionId);
        }
      });
      
      // 保存取消函数，以便在组件卸载时取消请求
      setCurrentStreamCancel(() => cancelStream);
      return cancelStream;
    } catch (error) {
      console.error('发送消息失败:', error);
      setIsTyping(false);
      setCurrentStreamCancel(null);
      // 如果发生异常，回退到普通请求
      handleFallbackMessage(input, userMessage.id, aiMessageId, sessionId);
    }
  };

  // 回退到普通聊天API的函数
  const handleFallbackMessage = async (input: string, userMessageId: string, aiMessageId: string, sessionId: string) => {
    try {
      // 调用普通聊天API
      const response = await chatAPI.sendMessage({
        message: input,
        modelId: selectedModel,
        knowledgeBaseId: knowledgeBaseEnabled ? selectedKnowledgeBase : undefined,
        useKnowledgeBase: knowledgeBaseEnabled
      });

      if (response.success) {
        // 更新AI消息
        setMessages(prev => prev.map(msg => 
          msg.id === aiMessageId 
            ? { 
                ...msg, 
                content: response.data.response,
                sources: response.data.sources || [],
                fromKnowledgeBase: knowledgeBaseEnabled
              }
            : msg
        ));
        
        // 保存AI响应到会话
        await saveMessageToSession(sessionId, response.data.response, 'assistant', {
          from_knowledge_base: knowledgeBaseEnabled,
          sources: response.data.sources || [],
          model_id: selectedModel,
          knowledge_base_id: knowledgeBaseEnabled ? selectedKnowledgeBase : null
        });
      } else {
        // 如果API调用失败，显示错误消息
        const errorMessage = `抱歉，处理您的消息时出现错误：${response.message}`;
        setMessages(prev => prev.map(msg => 
          msg.id === aiMessageId 
            ? {
                ...msg,
                content: errorMessage,
                fromKnowledgeBase: false,
                sources: []
              }
            : msg
        ));
        
        // 保存错误消息到会话
        await saveMessageToSession(sessionId, errorMessage, 'assistant', {
          error: true,
          model_id: selectedModel
        });
      }
    } catch (error) {
      console.error('发送消息失败:', error);
      // 如果发生异常，显示错误消息
      const errorMessage = '抱歉，网络连接出现问题，请稍后再试。';
      setMessages(prev => prev.map(msg => 
        msg.id === aiMessageId 
          ? {
              ...msg,
              content: errorMessage,
              fromKnowledgeBase: false,
              sources: []
            }
          : msg
      ));
      
      // 保存错误消息到会话
      await saveMessageToSession(sessionId, errorMessage, 'assistant', {
        error: true,
        model_id: selectedModel
      });
    } finally {
      setIsTyping(false);
    }
  };

  // 生成AI响应
  const generateAIResponse = (userInput: string): Message => {
    const input = userInput.toLowerCase();
    let baseResponse = '';
    let messageType: 'report' | 'followup' | 'explain' | 'similar' | 'prompt' | 'normal' = 'normal';
    
    // 生成诊断报告
    if (input.includes('生成报告') || input.includes('诊断报告')) {
      baseResponse = generateDiagnosisReport();
      messageType = 'report';
    }
    // 生成随访建议
    else if (input.includes('随访') || input.includes('随访建议')) {
      baseResponse = generateFollowUpRecommendations();
      messageType = 'followup';
    }
    // 解释术语
    else if (input.includes('解释') || input.includes('术语')) {
      // 提取用户想了解的术语
      const termMatch = input.match(/解释[""]?(.+?)[""]?/);
      const term = termMatch ? termMatch[1] : '糖尿病视网膜病变';
      baseResponse = generateTermExplanation(term);
      messageType = 'explain';
    }
    // 查找相似病例
    else if (input.includes('相似') || input.includes('病例')) {
      baseResponse = findSimilarCases();
      messageType = 'similar';
    }
    // 默认响应
    else {
      const defaultResponses = [
        '糖尿病视网膜病变是糖尿病最常见的微血管并发症之一，建议定期进行眼底检查。',
        '良好的血糖控制是预防并延缓糖尿病视网膜病变进展的关键。',
        '早期发现和治疗可以显著降低糖尿病视网膜病变导致的视力丧失风险。',
        '糖尿病患者即使没有视力问题，也应每年至少进行一次眼底检查。',
        '吸烟、高血压和高血脂会加重糖尿病视网膜病变的进展，应积极控制。'
      ];
      
      baseResponse = defaultResponses[Math.floor(Math.random() * defaultResponses.length)];
    }
    
    // 如果启用了知识库增强，则使用知识库内容增强回答
    let finalResponse = baseResponse;
    let sources: any[] = [];
    
    if (knowledgeBaseEnabled) {
      const enhancedResult = generateKnowledgeBaseEnhancedResponse(userInput, baseResponse);
      finalResponse = enhancedResult.response;
      sources = enhancedResult.sources;
    }
    
    return {
      id: Date.now().toString(),
      content: finalResponse,
      type: 'ai',
      timestamp: new Date(),
      messageType,
      fromKnowledgeBase: knowledgeBaseEnabled,
      sources
    };
  };

  // 导出聊天记录
  const handleExportChatHistory = async () => {
    if (!currentSessionId || messages.length === 0) {
      alert('没有可导出的聊天记录');
      return;
    }

    try {
      // 获取当前会话的完整消息历史
      const sessionData = await chatHistoryAPI.getSessionMessages(currentSessionId);
      
      // 创建导出内容
      const exportContent = {
        sessionId: currentSessionId,
        sessionTitle: sessions.find(s => s.id === currentSessionId)?.title || '未命名会话',
        exportDate: new Date().toISOString(),
        messages: sessionData.messages.map(msg => ({
          type: msg.type,
          content: msg.content,
          timestamp: msg.timestamp,
          messageType: msg.messageType
        }))
      };

      // 创建并下载JSON文件
      const dataStr = JSON.stringify(exportContent, null, 2);
      const dataUri = 'data:application/json;charset=utf-8,'+ encodeURIComponent(dataStr);
      
      const exportFileDefaultName = `chat_history_${currentSessionId}_${new Date().toISOString().split('T')[0]}.json`;
      
      const linkElement = document.createElement('a');
      linkElement.setAttribute('href', dataUri);
      linkElement.setAttribute('download', exportFileDefaultName);
      linkElement.click();
      
    } catch (error) {
      console.error('导出聊天记录失败:', error);
      alert('导出失败，请稍后重试');
    }
  };

  // 清空聊天记录
  const handleClearChat = async () => {
    // 创建新会话
    const newSessionId = await createNewSession();
    if (newSessionId) {
      setMessages([
        {
          id: '1',
          content: '您好！我是AI医学助手，可以回答关于糖尿病视网膜病变的问题。您可以询问医学知识，也可以输入"生成报告"、"随访建议"、"解释术语"或"相似病例"获取更多AI辅助功能。',
          type: 'ai',
          timestamp: new Date(),
          messageType: 'normal'
        }
      ]);
    }
  };

  // 处理键盘事件
  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  return (
    <div className="bg-gradient-to-br from-blue-50 via-white to-purple-50 min-h-screen flex flex-col">
      <Navbar />
      <div className="flex flex-1">
        <Sidebar />
        <main className="flex-1 ml-64 p-4">
          <div className="max-w-7xl mx-auto h-[calc(100vh-6rem)]">
            <motion.header 
              initial={{ opacity: 0, y: -20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5 }}
              className="mb-4"
            >
              <div className="bg-white rounded-xl shadow-md p-4 backdrop-blur-lg bg-opacity-90">
                <div className="flex justify-between items-center">
                  <div className="flex items-center space-x-3">
                    <div className="p-2 bg-gradient-to-br from-blue-500 to-purple-600 rounded-lg shadow-md">
                      <i className="fas fa-robot text-white text-xl"></i>
                    </div>
                    <div>
                      <h1 className="text-2xl font-bold bg-gradient-to-r from-blue-600 to-purple-600 bg-clip-text text-transparent">AI医学助手</h1>
                      <p className="text-gray-600 text-sm">获取关于糖尿病视网膜病变的专业医学建议</p>
                    </div>
                  </div>
                  <div className="flex space-x-2">
                    <motion.button
                      whileHover={{ scale: 1.05 }}
                      whileTap={{ scale: 0.95 }}
                      onClick={() => setShowHistory(!showHistory)}
                      className="px-3 py-1.5 bg-white border border-gray-300 rounded-lg font-medium text-gray-700 hover:bg-gray-50 transition-all flex items-center shadow-sm text-sm"
                    >
                      <i className="fas fa-history mr-1.5"></i>
                      聊天记录
                    </motion.button>
                    <motion.button
                      whileHover={{ scale: 1.05 }}
                      whileTap={{ scale: 0.95 }}
                      onClick={handleClearChat}
                      className="px-3 py-1.5 bg-white border border-gray-300 rounded-lg font-medium text-gray-700 hover:bg-gray-50 transition-all flex items-center shadow-sm text-sm"
                    >
                      <i className="fas fa-trash-alt mr-1.5"></i>
                      清空聊天
                    </motion.button>
                  </div>
                </div>
              </div>
            </motion.header>
            
            <div className="flex gap-3 h-[calc(100%-6rem)]">
              {/* 聊天历史记录侧边栏 */}
              <AnimatePresence>
                {showHistory && (
                  <motion.div
                    initial={{ opacity: 0, x: -20 }}
                    animate={{ opacity: 1, x: 0 }}
                    exit={{ opacity: 0, x: -20 }}
                    className="w-72 bg-white rounded-xl shadow-md p-3 overflow-y-auto"
                  >
                  <div className="flex justify-between items-center mb-3">
                    <h3 className="text-base font-semibold text-gray-800 flex items-center">
                      <i className="fas fa-history mr-2 text-blue-500"></i>
                      聊天历史记录
                    </h3>
                    <div className="flex space-x-1">
                      <motion.button
                        whileHover={{ scale: 1.05 }}
                        whileTap={{ scale: 0.95 }}
                        onClick={handleExportChatHistory}
                        disabled={!currentSessionId || messages.length === 0}
                        className={`p-1.5 rounded-lg transition-colors ${
                          currentSessionId && messages.length > 0
                            ? 'text-green-600 hover:bg-green-50'
                            : 'text-gray-400 cursor-not-allowed'
                        }`}
                        title="导出当前会话"
                      >
                        <i className="fas fa-download text-sm"></i>
                      </motion.button>
                      <motion.button
                        whileHover={{ scale: 1.05 }}
                        whileTap={{ scale: 0.95 }}
                        onClick={handleClearChat}
                        className="p-1.5 text-blue-600 hover:bg-blue-50 rounded-lg transition-colors"
                        title="新建会话"
                      >
                        <i className="fas fa-plus text-sm"></i>
                      </motion.button>
                    </div>
                  </div>
                  <div className="space-y-2">
                    {loadingSessions ? (
                      <div className="flex justify-center py-4">
                        <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-500"></div>
                      </div>
                    ) : chatSessions.length > 0 ? (
                      chatSessions.map((session) => (
                        <motion.div
                          key={session.id}
                          whileHover={{ scale: 1.02 }}
                          whileTap={{ scale: 0.98 }}
                          className={`p-2.5 rounded-lg border cursor-pointer transition-all ${
                            currentSessionId === session.id
                              ? 'border-blue-500 bg-blue-50'
                              : 'border-gray-200 hover:border-blue-300 hover:bg-blue-50'
                          }`}
                        >
                          <div className="flex justify-between items-start">
                            <div 
                              className="flex-1 min-w-0"
                              onClick={() => loadSessionMessages(session.id)}
                            >
                              <h4 className="font-medium text-gray-800 text-sm truncate">{session.title}</h4>
                              <p className="text-xs text-gray-500 mt-0.5 truncate">{session.lastMessage || '暂无消息'}</p>
                              <p className="text-xs text-gray-400 mt-1">
                                {new Date(session.updatedAt).toLocaleDateString('zh-CN', {
                                  year: 'numeric',
                                  month: 'short',
                                  day: 'numeric',
                                  hour: '2-digit',
                                  minute: '2-digit'
                                })}
                              </p>
                            </div>
                            <motion.button
                              whileHover={{ scale: 1.1 }}
                              whileTap={{ scale: 0.9 }}
                              onClick={(e) => {
                                e.stopPropagation();
                                if (window.confirm('确定要删除这个会话吗？')) {
                                  deleteSession(session.id);
                                }
                              }}
                              className="ml-1.5 p-1 text-red-500 hover:text-red-700 hover:bg-red-50 rounded-lg transition-colors"
                              title="删除会话"
                            >
                              <i className="fas fa-trash-alt text-xs"></i>
                            </motion.button>
                          </div>
                        </motion.div>
                      ))
                    ) : (
                      <div className="text-center py-6 text-gray-500">
                        <i className="fas fa-inbox text-2xl mb-2"></i>
                        <p className="text-sm">暂无聊天记录</p>
                      </div>
                    )}
                  </div>
                </motion.div>
                )}
              </AnimatePresence>
              
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5, delay: 0.2 }}
                className={`bg-white rounded-xl shadow-md border border-gray-100 overflow-hidden flex flex-col ${showHistory ? 'flex-1' : 'w-full'}`}
              >
                {/* 聊天头部 - 添加模型和知识库选择 */}
                <div className="p-3 border-b border-gray-200 bg-gradient-to-r from-blue-50 to-indigo-50 rounded-t-xl shadow-sm flex-shrink-0">
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center space-x-2">
                        <div className="w-8 h-8 bg-gradient-to-br from-blue-500 to-indigo-600 rounded-full flex items-center justify-center text-white shadow-md">
                          <i className="fas fa-user-md text-sm"></i>
                        </div>
                        <div>
                          <h2 className="text-base font-semibold text-gray-800">AI医疗助手</h2>
                          <p className="text-xs text-green-600 flex items-center">
                            <span className="w-1.5 h-1.5 bg-green-500 rounded-full mr-1"></span>
                            在线
                          </p>
                        </div>
                      </div>
                      <button
                        onClick={() => setShowHistory(!showHistory)}
                        className="p-1.5 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition-colors"
                      >
                        <i className="fas fa-history text-sm"></i>
                      </button>
                    </div>
                    
                    {/* 模型和知识库选择区域 */}
                    <div className={`grid gap-2 mt-2 ${knowledgeBaseEnabled ? 'grid-cols-2' : 'grid-cols-1'}`}>
                      {/* 模型选择 */}
                      <div>
                        <label className="block text-xs font-medium text-gray-700 mb-0.5">选择对话模型</label>
                        <select
                          value={selectedModel}
                          onChange={(e) => setSelectedModel(e.target.value)}
                          disabled={loadingModels}
                          className="w-full px-2 py-1.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 bg-white text-xs"
                        >
                          {loadingModels ? (
                            <option value="">加载中...</option>
                          ) : models.length > 0 ? (
                            models.filter(model => model.type === 'chat').map((model) => (
                              <option key={model.id} value={model.id}>
                                {model.name} {model.isDefault && '(默认)'}
                              </option>
                            ))
                          ) : (
                            <option value="">无可用模型</option>
                          )}
                        </select>
                      </div>
                      
                      {/* 知识库选择 - 只在启用知识库增强功能时显示 */}
                      {knowledgeBaseEnabled && (
                        <div>
                          <label className="block text-xs font-medium text-gray-700 mb-0.5">选择知识库</label>
                          <select
                            value={selectedKnowledgeBase}
                            onChange={(e) => setSelectedKnowledgeBase(e.target.value)}
                            disabled={loadingKnowledgeBases}
                            className="w-full px-2 py-1.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 bg-white text-xs"
                          >
                            {loadingKnowledgeBases ? (
                              <option value="">加载中...</option>
                            ) : knowledgeBases.length > 0 ? (
                              knowledgeBases.map((kb) => (
                                <option key={kb.id} value={kb.id}>
                                  {kb.name} ({kb.status === 'active' ? '活跃' : '已归档'})
                                </option>
                              ))
                            ) : (
                              <option value="">无可用知识库</option>
                            )}
                          </select>
                        </div>
                      )}
                    </div>
                  </div>
                  
                  {/* 聊天消息区域 */}
                  <div className="flex-1 overflow-y-auto p-2 space-y-2 bg-gradient-to-b from-gray-50 to-white" style={{ height: 'calc(100% - 140px)' }}>
                    {messages.length === 0 ? (
                      <motion.div 
                        initial={{ opacity: 0, y: 20 }}
                        animate={{ opacity: 1, y: 0 }}
                        className="flex flex-col items-center justify-center h-full text-center p-4"
                      >
                        <div className="w-12 h-12 bg-gradient-to-br from-blue-100 to-indigo-100 rounded-full flex items-center justify-center mb-2">
                          <i className="fas fa-comments text-xl text-blue-600"></i>
                        </div>
                        <h3 className="text-base font-semibold text-gray-700 mb-2">欢迎使用AI医疗助手</h3>
                        <p className="text-gray-500 mb-3 max-w-md text-xs">我可以帮助您解答医学问题，提供诊断建议，或者生成医疗报告</p>
                        <div className="flex flex-wrap justify-center gap-1.5 max-w-lg">
                          <button 
                            onClick={() => setInput("糖尿病视网膜病变的分期")}
                            className="px-2 py-1 bg-white border border-gray-200 rounded-full text-xs text-gray-700 hover:bg-gray-50 shadow-sm transition-colors"
                          >
                            糖尿病视网膜病变的分期
                          </button>
                          <button 
                            onClick={() => setInput("生成报告")}
                            className="px-2 py-1 bg-white border border-gray-200 rounded-full text-xs text-gray-700 hover:bg-gray-50 shadow-sm transition-colors"
                          >
                            生成报告
                          </button>
                          <button 
                            onClick={() => setInput("随访建议")}
                            className="px-2 py-1 bg-white border border-gray-200 rounded-full text-xs text-gray-700 hover:bg-gray-50 shadow-sm transition-colors"
                          >
                            随访建议
                          </button>
                          <button 
                            onClick={() => setInput("解释术语")}
                            className="px-2 py-1 bg-white border border-gray-200 rounded-full text-xs text-gray-700 hover:bg-gray-50 shadow-sm transition-colors"
                          >
                            解释术语
                          </button>
                        </div>
                      </motion.div>
                    ) : (
                      messages.map((message) => (
                        <motion.div
                          key={message.id}
                          initial={{ opacity: 0, y: 20 }}
                          animate={{ opacity: 1, y: 0 }}
                          transition={{ duration: 0.3 }}
                          className={`flex ${message.type === 'user' ? 'justify-end' : 'justify-start'}`}
                        >
                          {message.type === 'ai' && (
                            <div className="flex-shrink-0 w-6 h-6 bg-gradient-to-br from-blue-500 to-indigo-600 rounded-full flex items-center justify-center text-white text-xs mr-2 shadow-sm">
                              <i className="fas fa-robot text-xs"></i>
                            </div>
                          )}
                          
                          <div className={`max-w-[80%] ${message.type === 'user' ? 'text-right' : 'text-left'}`}>
                            {message.type === 'ai' && (
                              <div className="inline-block p-2 rounded-xl bg-white text-gray-900 rounded-tl-none shadow-sm border border-gray-100">
                                {message.fromKnowledgeBase && (
                                  <motion.div 
                                    initial={{ opacity: 0, scale: 0.9 }}
                                    animate={{ opacity: 1, scale: 1 }}
                                    transition={{ delay: 0.2 }}
                                    className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800 mb-2"
                                  >
                                    <i className="fas fa-database mr-1 text-xs"></i>
                                    知识库增强回答
                                  </motion.div>
                                )}
                                <div className="whitespace-pre-line text-xs leading-relaxed">
                                  {message.content}
                                </div>
                                {message.fromKnowledgeBase && message.sources && message.sources.length > 0 && (
                                  <div className="mt-2 pt-2 border-t border-gray-200">
                                    <div className="text-xs text-gray-500 mb-1">
                                      引用归属：
                                      {message.sources.map((source, index) => (
                                        <span key={index}>
                                          <button
                                            onClick={() => toggleSourceExpansion(message.id, source.id || source.document_id)}
                                            className="text-blue-600 hover:text-blue-800 hover:underline cursor-pointer ml-1"
                                          >
                                            {source.title}
                                          </button>
                                          {index < message.sources!.length - 1 && '，'}
                                        </span>
                                      ))}
                                    </div>
                                    {message.sources.map((source, index) => {
                                      const sourceId = source.id || source.document_id;
                                      const isExpanded = expandedSources[`${message.id}_${sourceId}`];
                                      return (
                                        <div key={index} className="mt-1">
                                          {isExpanded && (
                                            <div className="bg-blue-50 p-2 rounded-lg border border-blue-200">
                                              <div className="text-xs font-medium text-blue-800 mb-1">
                                                {source.title}
                                              </div>
                                              <div className="text-xs text-gray-700 whitespace-pre-line">
                                                {source.content}
                                              </div>
                                            </div>
                                          )}
                                        </div>
                                      );
                                    })}
                                  </div>
                                )}
                              </div>
                            )}
                            
                            {message.type === 'user' && (
                              <div className="inline-block p-2 rounded-xl bg-gradient-to-br from-blue-600 to-blue-700 text-white rounded-tr-none shadow-sm">
                                <p className="text-xs">{message.content}</p>
                              </div>
                            )}
                          </div>
                          
                          {message.type === 'user' && (
                            <div className="flex-shrink-0 w-6 h-6 bg-gradient-to-br from-gray-400 to-gray-600 rounded-full flex items-center justify-center text-white text-xs ml-2 shadow-sm">
                              <i className="fas fa-user text-xs"></i>
                            </div>
                          )}
                        </motion.div>
                      ))
                    )}
                  
                  {isTyping && (
                    <motion.div 
                      initial={{ opacity: 0, y: 20 }}
                      animate={{ opacity: 1, y: 0 }}
                      className="flex justify-start"
                    >
                      <div className="flex-shrink-0 w-6 h-6 bg-gradient-to-br from-blue-500 to-indigo-600 rounded-full flex items-center justify-center text-white text-xs mr-2 shadow-sm">
                        <i className="fas fa-robot text-xs"></i>
                      </div>
                      <div className="inline-block p-3 rounded-xl bg-white text-gray-900 rounded-tl-none shadow-md border border-gray-100">
                        <div className="flex space-x-1">
                          <motion.div 
                            className="w-1.5 h-1.5 bg-gray-400 rounded-full"
                            animate={{ scale: [1, 1.2, 1] }}
                            transition={{ duration: 0.8, repeat: Infinity, delay: 0 }}
                          ></motion.div>
                          <motion.div 
                            className="w-1.5 h-1.5 bg-gray-400 rounded-full"
                            animate={{ scale: [1, 1.2, 1] }}
                            transition={{ duration: 0.8, repeat: Infinity, delay: 0.2 }}
                          ></motion.div>
                          <motion.div 
                            className="w-1.5 h-1.5 bg-gray-400 rounded-full"
                            animate={{ scale: [1, 1.2, 1] }}
                            transition={{ duration: 0.8, repeat: Infinity, delay: 0.4 }}
                          ></motion.div>
                        </div>
                      </div>
                    </motion.div>
                  )}
                
                  <div ref={messagesEndRef} />
                </div>
                
                {/* 输入区域 */}
                <div className="p-2 border-t border-gray-200 bg-gray-50 flex-shrink-0">
                  {/* 快捷功能按钮 */}
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center space-x-2">
                      <label className="relative inline-flex items-center cursor-pointer">
                        <input 
                          type="checkbox" 
                          checked={knowledgeBaseEnabled}
                          onChange={(e) => setKnowledgeBaseEnabled(e.target.checked)}
                          className="sr-only peer"
                        />
                        <div className="w-8 h-4 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-blue-300 rounded-full peer peer-checked:after:translate-x-4 peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-3 after:w-3 after:transition-all peer-checked:bg-blue-600"></div>
                        <span className="ml-2 text-xs font-medium text-gray-700">知识库增强</span>
                      </label>
                      {knowledgeBaseEnabled && (
                        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800">
                          <i className="fas fa-database mr-1 text-xs"></i>
                          已启用
                        </span>
                      )}
                    </div>
                    
                    {/* 功能按钮组 */}
                    <div className="flex items-center space-x-1">
                      <motion.button
                        whileHover={{ scale: 1.05 }}
                        whileTap={{ scale: 0.95 }}
                        onClick={() => setInput("生成报告")}
                        className="p-1.5 text-gray-500 hover:text-blue-600 hover:bg-blue-50 rounded-lg transition-colors"
                        title="生成诊断报告"
                      >
                        <i className="fas fa-file-medical text-xs"></i>
                      </motion.button>
                      <motion.button
                        whileHover={{ scale: 1.05 }}
                        whileTap={{ scale: 0.95 }}
                        onClick={() => setInput("随访建议")}
                        className="p-1.5 text-gray-500 hover:text-green-600 hover:bg-green-50 rounded-lg transition-colors"
                        title="获取随访建议"
                      >
                        <i className="fas fa-calendar-check text-xs"></i>
                      </motion.button>
                      <motion.button
                        whileHover={{ scale: 1.05 }}
                        whileTap={{ scale: 0.95 }}
                        onClick={() => setInput("解释术语")}
                        className="p-1.5 text-gray-500 hover:text-yellow-600 hover:bg-yellow-50 rounded-lg transition-colors"
                        title="解释医学术语"
                      >
                        <i className="fas fa-book-open text-xs"></i>
                      </motion.button>
                      <motion.button
                        whileHover={{ scale: 1.05 }}
                        whileTap={{ scale: 0.95 }}
                        onClick={() => setInput("相似病例")}
                        className="p-1.5 text-gray-500 hover:text-purple-600 hover:bg-purple-50 rounded-lg transition-colors"
                        title="查找相似病例"
                      >
                        <i className="fas fa-search text-xs"></i>
                      </motion.button>
                      <motion.button
                        whileHover={{ scale: 1.05 }}
                        whileTap={{ scale: 0.95 }}
                        onClick={() => {
                          if (messages.length > 0) {
                            const newMessages = [...messages];
                            newMessages.pop(); // 删除最后一条消息
                            setMessages(newMessages);
                          }
                        }}
                        className="p-1.5 text-gray-500 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors"
                        title="撤回上一条消息"
                      >
                        <i className="fas fa-undo text-xs"></i>
                      </motion.button>
                      <motion.button
                        whileHover={{ scale: 1.05 }}
                        whileTap={{ scale: 0.95 }}
                        onClick={() => {
                          setMessages([]);
                          setInput('');
                        }}
                        className="p-1.5 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition-colors"
                        title="清空对话"
                      >
                        <i className="fas fa-trash text-xs"></i>
                      </motion.button>
                    </div>
                  </div>
                  <div className="flex space-x-2">
                    <input
                      type="text"
                      value={input}
                      onChange={(e) => setInput(e.target.value)}
                      onKeyPress={handleKeyPress}
                      placeholder={knowledgeBaseEnabled ? "输入您的问题（知识库增强已启用）..." : "输入您的问题..."}
                      className="flex-1 px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-all text-sm"
                      disabled={isTyping}
                    />
                    <motion.button
                      whileHover={{ scale: 1.05 }}
                      whileTap={{ scale: 0.95 }}
                      onClick={handleSendMessage}
                      disabled={!input.trim() || isTyping}
                      className={`p-2 bg-blue-600 text-white rounded-lg transition-colors ${
                        (!input.trim() || isTyping) 
                          ? 'opacity-50 cursor-not-allowed' 
                          : 'hover:bg-blue-700'
                      }`}
                    >
                      <i className="fas fa-paper-plane text-sm"></i>
                    </motion.button>
                  </div>
                  <p className="text-xs text-gray-500 mt-1 text-center">
                    提示：您可以询问医学知识，也可以使用上方快捷按钮获取更多AI辅助功能
                  </p>
                </div>
              </motion.div>
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}

// 模拟知识库文章数据
const mockKnowledgeArticles = [
  {
    id: '1',
    title: '糖尿病视网膜病变的分期与治疗',
    content: '糖尿病视网膜病变（DR）是糖尿病最常见的微血管并发症之一。根据国际临床分级标准，DR可分为非增殖期（NPDR）和增殖期（PDR）...\n\n非增殖期糖尿病视网膜病变（NPDR）包括：\n1. 轻度NPDR：仅有微动脉瘤\n2. 中度NPDR：微动脉瘤、视网膜内出血、硬性渗出\n3. 重度NPDR：满足以下任一条件（4-2-1规则）：\n   - 各象限视网膜内出血≥20处\n   - 静脉串珠样改变≥2个象限\n   - 显著的视网膜内微血管异常≥1个象限\n\n增殖期糖尿病视网膜病变（PDR）特征：\n- 新生血管形成\n- 玻璃体/视网膜前出血\n\n治疗原则：\n1. 轻度NPDR：控制血糖、血压、血脂，定期随访\n2. 中度至重度NPDR：考虑激光光凝治疗\n3. PDR：立即进行全视网膜光凝（PRP）或抗VEGF治疗',
    category: '疾病知识',
    tags: ['糖尿病', '视网膜病变', '分期', '治疗']
  },
  {
    id: '2',
    title: '抗VEGF药物在眼底疾病中的应用',
    content: '抗血管内皮生长因子（抗VEGF）药物已成为治疗多种眼底疾病的一线治疗方案。目前临床常用的抗VEGF药物包括贝伐珠单抗（Avastin）、雷珠单抗（Lucentis）和阿柏西普（Eylea）。\n\n适应症：\n1. 湿性年龄相关性黄斑变性（wAMD）\n2. 糖尿病黄斑水肿（DME）\n3. 视网膜静脉阻塞继发黄斑水肿（RVO-ME）\n4. 脉络膜新生血管（CNV）\n\n给药方案：\n- 初始治疗：每月1次，连续3次\n- 维持治疗：按需治疗（PRN）或治疗与延长（T&E）方案\n\n注意事项：\n1. 注射前需评估眼表和眼内感染风险\n2. 监测眼压变化\n3. 长期治疗需关注系统性心血管风险',
    category: '治疗方法',
    tags: ['抗VEGF', '贝伐珠单抗', '雷珠单抗', '阿柏西普']
  },
  {
    id: '3',
    title: 'OCT影像解读指南',
    content: '光学相干断层扫描（OCT）是眼底疾病诊断的重要工具。正确解读OCT影像对临床决策至关重要。\n\n正常视网膜OCT结构：\n1. 内界膜（ILM）\n2. 神经纤维层（NFL）\n3. 神经节细胞层（GCL）\n4. 内丛状层（IPL）\n5. 内核层（INL）\n6. 外丛状层（OPL）\n7. 外核层（ONL）\n8. 外界膜（ELM）\n9. 视细胞内外节（IS/OS）\n10. 视网膜色素上皮（RPE）\n11. 脉络膜毛细血管层\n\n常见病变的OCT表现：\n1. 黄斑水肿：视网膜增厚，囊腔形成\n2. 视网膜前膜：视网膜表面高反射膜\n3. 黄斑裂孔：视网膜全层缺损\n4. 脉络膜新生血管：RPE层抬高，下方中低反射',
    category: '影像诊断',
    tags: ['OCT', '影像解读', '黄斑', '视网膜']
  }
];

// 搜索知识库相关文章
const searchKnowledgeBase = (query: string): { article: any, relevance: number }[] => {
  if (!query.trim()) return [];
  
  const queryLower = query.toLowerCase();
  const results: { article: any, relevance: number }[] = [];
  
  mockKnowledgeArticles.forEach(article => {
    let relevance = 0;
    
    // 标题匹配权重最高
    if (article.title.toLowerCase().includes(queryLower)) {
      relevance += 10;
    }
    
    // 标签匹配权重较高
    article.tags.forEach(tag => {
      if (tag.toLowerCase().includes(queryLower)) {
        relevance += 5;
      }
    });
    
    // 内容匹配
    const contentMatches = (article.content.toLowerCase().match(new RegExp(queryLower, 'g')) || []).length;
    relevance += contentMatches * 0.5;
    
    if (relevance > 0) {
      results.push({ article, relevance });
    }
  });
  
  // 按相关性排序
  return results.sort((a, b) => b.relevance - a.relevance).slice(0, 2); // 只返回前2个最相关的结果
};

// 生成知识库增强的AI响应
const generateKnowledgeBaseEnhancedResponse = (userInput: string, baseResponse: string): { response: string, sources: any[] } => {
  const relevantArticles = searchKnowledgeBase(userInput);
  
  if (relevantArticles.length === 0) {
    return { response: baseResponse, sources: [] };
  }
  
  const sources = relevantArticles.map(result => ({
    id: result.article.id,
    title: result.article.title,
    content: result.article.content,
    category: result.article.category,
    tags: result.article.tags,
    relevance: result.relevance
  }));
  
  // 只返回基础响应，引用内容将在UI中单独显示
  return { response: baseResponse, sources };
};