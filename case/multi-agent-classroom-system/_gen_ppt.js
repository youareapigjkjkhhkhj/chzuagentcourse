const pptxgen = require('pptxgenjs');
const pptx = new pptxgen();
pptx.layout = 'LAYOUT_16x9';
pptx.defineSlideMaster({
  title: 'MASTER',
  background: { color: 'FBF7EE' },
  objects: [],
});

const S = pptx.ShapeType;
const C = {
  bg: 'FBF7EE', card: 'F4EDE0', card2: 'F9F5EC',
  accent: 'B98A5A', accent2: '6E8F5E', accent3: '8A7BB0',
  ink: '3D3730', sub: '6B6457', muted: '8C8575',
  line: 'D9CCB9', white: 'FFFFFF', deep: '7A5B3A',
};
const F = 'Microsoft YaHei';

function bg(s) { s.background = { color: C.bg }; }
function rrect(s, x, y, w, h, fill, line, rad) {
  const o = { x, y, w, h, rectRadius: rad || 0.08, fill: { color: fill } };
  if (line) o.line = { color: line, width: 0.75 };
  s.addShape(S.roundRect, o);
}
function rect(s, x, y, w, h, fill, line) {
  const o = { x, y, w, h, fill: { color: fill } };
  if (line) o.line = { color: line, width: 0.75 };
  s.addShape(S.rect, o);
}
function ellipse(s, x, y, w, h, fill) {
  s.addShape(S.ellipse, { x, y, w, h, fill: { color: fill } });
}
function line(s, x1, y1, x2, y2, color, w) {
  s.addShape(S.line, { x: x1, y: y1, w: x2 - x1, h: y2 - y1, line: { color, width: w || 1 } });
}
function txt(s, x, y, w, h, text, o) {
  s.addText(text, Object.assign({ x, y, w, h, fontFace: F, color: C.ink }, o));
}
function header(s, kicker, title, subtitle) {
  rect(s, 0.55, 0.44, 0.09, 0.62, C.accent);
  txt(s, 0.78, 0.38, 8.6, 0.32, kicker, { fontSize: 12, color: C.accent, bold: true, charSpacing: 3 });
  txt(s, 0.78, 0.66, 8.6, 0.5, title, { fontSize: 25, bold: true, color: C.ink });
  if (subtitle) txt(s, 0.78, 1.16, 8.6, 0.28, subtitle, { fontSize: 12.5, color: C.sub });
  line(s, 0.55, 1.5, 9.45, 1.5, C.line, 0.75);
}
function footer(s, n) {
  txt(s, 0.55, 5.3, 4, 0.25, 'EduAgentX · 多智能体互动课堂', { fontSize: 9, color: C.muted });
  txt(s, 9.05, 5.3, 0.5, 0.25, String(n), { fontSize: 10, bold: true, color: C.accent, align: 'right' });
}
function page(n, kicker, title, subtitle, fn) {
  const s = pptx.addSlide();
  bg(s); header(s, kicker, title, subtitle); fn(s); footer(s, n);
}
function chip(s, x, y, w, text, fill, color) {
  rrect(s, x, y, w, 0.36, fill, null, 0.06);
  txt(s, x, y + 0.07, w, 0.24, text, { fontSize: 10.5, color: color || C.ink, align: 'center', bold: true });
}

// ================= P1 COVER =================
(function () {
  const s = pptx.addSlide();
  bg(s);
  ellipse(s, 7.7, -0.75, 3.0, 3.0, 'F0E4CF');
  ellipse(s, -0.7, 4.1, 2.6, 2.6, 'EDDFC6');
  ellipse(s, 0.35, 0.45, 0.5, 0.5, C.accent);
  txt(s, 0.55, 0.4, 6, 0.5, 'EduAgentX', { fontSize: 20, bold: true, color: C.deep });
  txt(s, 0.55, 0.83, 6, 0.3, 'Open Multi-Agent Interactive Classroom', { fontSize: 10, color: C.muted, charSpacing: 1 });
  line(s, 0.55, 1.18, 3.4, 1.18, C.accent, 2);
  txt(s, 0.55, 1.42, 8.2, 1.7,
    [{ text: '多智能体互动课堂', options: { fontSize: 44, bold: true, color: C.ink } },
     { text: '  项目说明', options: { fontSize: 34, color: C.accent, bold: true } }],
    { lineSpacingMultiple: 1.05 });
  txt(s, 0.55, 2.95, 8.4, 0.9,
    '输入一个主题，AI 教师与 AI 同学陪你上一堂完整的课。\n一键生成课件与讲稿、实时讨论、白板互动与多格式导出。',
    { fontSize: 15, color: C.sub, lineSpacingMultiple: 1.35 });
  const chips = [['26+', '已生成课堂'], ['4', '核心模块'], ['3', 'AI 同学/班'], ['5', '导出格式']];
  let cx = 0.55;
  chips.forEach((c) => {
    const w = 1.8;
    rrect(s, cx, 4.05, w, 0.95, C.card, null, 0.12);
    txt(s, cx, 4.17, w, 0.4, c[0], { fontSize: 24, bold: true, color: C.accent, align: 'center' });
    txt(s, cx, 4.62, w, 0.26, c[1], { fontSize: 11, color: C.sub, align: 'center' });
    cx += 2.0;
  });
  txt(s, 5.0, 5.3, 4.5, 0.25, '产品设计原型 · 高保真演示', { fontSize: 9, color: C.muted, align: 'right' });
})();

// ================= P2 项目概述 =================
page(2, 'OVERVIEW', '项目概述', '多智能体驱动的互动智能课堂平台，一键生成完整课堂体验', function (s) {
  const box1 = 0.55, box2 = 5.1;
  rrect(s, box1, 1.78, 4.35, 1.9, C.card2, C.line, 0.12);
  txt(s, box1 + 0.3, 1.95, 3.8, 0.3, '一句话定义', { fontSize: 15, bold: true, color: C.accent });
  txt(s, box1 + 0.3, 2.35, 3.8, 1.2,
    '用户只需输入学习主题或上传材料，系统自动生成含幻灯片、测验、交互模拟与项目式学习的完整课堂，并由多个 AI 角色进行语音讲解、白板板书与实时讨论。',
    { fontSize: 12, color: C.sub, lineSpacingMultiple: 1.4, valign: 'top' });

  rrect(s, box2, 1.78, 4.35, 1.9, C.card2, C.line, 0.12);
  txt(s, box2 + 0.3, 1.95, 3.8, 0.3, '核心价值主张', { fontSize: 15, bold: true, color: C.accent2 });
  txt(s, box2 + 0.3, 2.35, 3.8, 1.2,
    '把' + 'AI 教师 + 多个 AI 同学' + '带入同一间课堂，还原真实同伴学习氛围，实现可干预、可扩展、可导出的沉浸式教学。',
    { fontSize: 12, color: C.sub, lineSpacingMultiple: 1.4, valign: 'top' });

  const feats = [
    ['一键生成', '主题→完整课堂', C.accent],
    ['多智能体', '教师+同学协作', C.accent2],
    ['实时互动', '讨论·白板·语音', C.accent3],
    ['灵活导出', 'PPTX/HTML/视频', C.accent],
  ];
  let fx = 0.55;
  feats.forEach((f) => {
    rrect(s, fx, 3.95, 2.02, 1.15, C.card, null, 0.1);
    ellipse(s, fx + 0.2, 4.1, 0.32, 0.32, f[2]);
    txt(s, fx + 0.64, 4.1, 1.4, 0.3, f[0], { fontSize: 12.5, bold: true, color: C.ink });
    txt(s, fx + 0.2, 4.55, 1.7, 0.4, f[1], { fontSize: 10, color: C.sub, lineSpacingMultiple: 1.2 });
    fx += 2.18;
  });
});

// ================= P3 背景与痛点 =================
page(3, 'BACKGROUND', '背景与痛点', 'AI 能力成熟，但线上课堂仍缺' + '一堂完整的课', function (s) {
  txt(s, 0.55, 1.7, 8.9, 0.3, '当 AI 已能生成课件，真正的瓶颈是什么？', { fontSize: 14, bold: true, color: C.ink });
  const cols = [
    { t: '内容割裂', d: '大多数工具只能生成静态幻灯片，缺少讲稿、板书记录与实时讨论，学习体验单向。', c: C.accent },
    { t: '缺乏互动', d: '线上课堂多是视频回放，没有同伴交流、随堂提问与即时反馈，难以形成沉浸氛围。', c: C.accent2 },
    { t: '难以干预', d: '生成后很难按需微调，用户无法在过程中持续对话、补材料或修改某个环节。', c: C.accent3 },
    { t: '资产难复用', d: '音视频、图片、文档等素材难以统一管理，导出与二次利用繁琐。', c: C.accent },
  ];
  let cx = 0.55;
  cols.forEach((col) => {
    rrect(s, cx, 2.15, 2.02, 2.65, C.card2, C.line, 0.12);
    ellipse(s, cx + 0.24, 2.35, 0.42, 0.42, col.c);
    txt(s, cx + 0.78, 2.35, 1.3, 0.4, col.t, { fontSize: 13, bold: true, color: C.ink });
    txt(s, cx + 0.24, 2.95, 1.6, 1.7, col.d, { fontSize: 10.5, color: C.sub, lineSpacingMultiple: 1.35, valign: 'top' });
    cx += 2.18;
  });
  txt(s, 0.55, 4.95, 8.9, 0.3, '→ 解法：以多智能体编排为核心，把生成、讲授、互动、导出串成一堂完整可干预的课。', { fontSize: 12.5, bold: true, color: C.accent });
});

// ================= P4 核心目标 =================
page(4, 'GOALS', '核心目标', '构建从生成到讲授再到导出的端到端智能课堂', function (s) {
  const goals = [
    ['一键转化', '任意主题一键转化为结构完整、可直接开讲的互动课堂', C.accent],
    ['多智能体协作', 'AI 教师授课 + 多位 AI 同学实时提问、辩论与补充，还原同伴学习', C.accent2],
    ['可干预工作台', '聊天式生成 Agent，支持打断、提要求、补材料与随时人工编辑', C.accent3],
    ['多媒体能力', '语音讲解、语音识别、图像与视频生成，提供沉浸式体验', C.accent],
    ['灵活导出', '可编辑 PPTX、交互式 HTML、课程视频，覆盖离线与回看', C.accent2],
    ['可扩展部署', 'Provider 中立 + 本地/云端混合部署，支持插件式扩展', C.accent3],
  ];
  let x = 0.55, y = 1.75, idx = 0;
  goals.forEach((g) => {
    const col = idx % 2, row = Math.floor(idx / 2);
    const gx = 0.55 + col * 4.48, gy = 1.75 + row * 1.18;
    rrect(s, gx, gy, 4.3, 1.02, C.card2, C.line, 0.1);
    ellipse(s, gx + 0.22, gy + 0.3, 0.4, 0.4, g[2]);
    txt(s, gx + 0.74, gy + 0.26, 1.0, 0.4, String(idx + 1).padStart(2, '0'), { fontSize: 16, bold: true, color: g[2] });
    txt(s, gx + 0.22, gy + 0.72, 2.2, 0.3, g[0], { fontSize: 12.5, bold: true, color: C.ink });
    txt(s, gx + 2.1, gy + 0.22, 2.1, 0.7, g[1], { fontSize: 10.5, color: C.sub, lineSpacingMultiple: 1.2, valign: 'top' });
    idx++;
  });
});

// ================= P5 适用场景 =================
page(5, 'SCENARIOS', '适用场景', '面向多种教育形态的通用课堂平台', function (s) {
  const sc = [
    ['在线教育', '为高校与培训机构提供可交互的在线课程，增强学习黏性', C.accent],
    ['企业培训', '把新员工培训、合规学习转化为生动的互动课堂', C.accent2],
    ['个人自学', '输入主题即获得一次完整的讲解 + 讨论体验', C.accent3],
    ['职业技能', '动手型课程可嵌入代码、模拟实验与项目式学习', C.accent],
    ['翻转课堂', '课前自主完成互动学习，课中聚焦讨论与实践', C.accent2],
    ['终身学习', '低门槛主题学习，anytime 随时开展一段沉浸学习', C.accent3],
  ];
  let xx = 0.55, yy = 1.78;
  sc.forEach((item, i) => {
    const x = 0.55 + (i % 3) * 3.05, y = 1.78 + Math.floor(i / 3) * 1.7;
    rrect(s, x, y, 2.85, 1.55, C.card, null, 0.12);
    txt(s, x + 0.26, y + 0.24, 2.4, 0.3, item[0], { fontSize: 13.5, bold: true, color: item[2] });
    txt(s, x + 0.26, y + 0.62, 2.4, 0.8, item[1], { fontSize: 11, color: C.sub, lineSpacingMultiple: 1.3, valign: 'top' });
  });
  txt(s, 0.55, 5.0, 8.9, 0.4, '无论在哪里学习，都能' + '让 AI 教师与 AI 同学' + '陪你走进同一间课堂。', { fontSize: 13, bold: true, color: C.accent, align: 'center' });
});

// ================= P6 系统总览架构 =================
page(6, 'ARCHITECTURE', '系统总体架构', '分层架构，以多智能体编排与课堂运行时为核心', function (s) {
  // 层级块
  const layers = [
    { t: '用户入口层', d: 'Web 前端 · 即时通讯机器人 · API 接口', c: C.accent, y: 1.72 },
    { t: '应用服务层', d: '课程生成 · 工作台 · 编辑器 · 播放器 · 用户设置', c: C.accent2, y: 2.36 },
    { t: '多智能体编排与生成引擎', d: '状态机编排 + Skills · 材料解析 + 工具调用', c: C.accent3, y: 3.0 },
    { t: '课堂运行时与交互引擎', d: '幻灯片 / 测验 / 交互 · 白板 · 语音 · 讨论', c: C.accent, y: 3.64 },
    { t: '能力抽象层（可插拔）', d: '大模型 · 语音合成/识别 · 图像/视频 · 搜索 · 文档解析', c: C.accent2, y: 4.28 },
  ];
  layers.forEach((L) => {
    rrect(s, 0.55, L.y, 6.0, 0.56, C.card2, C.line, 0.09);
    rect(s, 0.55, L.y, 0.09, 0.56, L.c);
    txt(s, 0.78, L.y + 0.06, 2.7, 0.44, L.t, { fontSize: 13, bold: true, color: C.ink });
    txt(s, 3.45, L.y + 0.1, 3.0, 0.36, L.d, { fontSize: 9.5, color: C.sub });
  });
  // 右侧能力列表
  rrect(s, 6.85, 1.72, 2.6, 3.1, C.card, null, 0.1);
  txt(s, 7.05, 1.86, 2.3, 0.3, '支撑能力', { fontSize: 12, bold: true, color: C.accent });
  const caps = ['大语言模型', '语音合成 TTS', '语音识别 ASR', '图像 / 视频生成', '网络搜索', '文档解析'];
  caps.forEach((cap, i) => {
    ellipse(s, 7.08, 2.26 + i * 0.42, 0.16, 0.16, C.accent2);
    txt(s, 7.32, 2.2 + i * 0.42, 2.1, 0.3, cap, { fontSize: 11, color: C.sub });
  });
  // 底部数据/渲染
  rrect(s, 0.55, 4.92, 8.9, 0.42, C.card2, C.line, 0.08);
  txt(s, 0.8, 5.0, 8.5, 0.28, '数据与资产层 · 渲染与导出服务 → 数据库 / 对象存储 · 视频导出 / PPTX 生成', { fontSize: 10.5, color: C.sub, align: 'center' });
});

// ================= P7 课程生成引擎 =================
page(7, 'GENERATOR', '课程生成引擎', '一键生成 + Agent 工作台两种模式，灵活可干预', function (s) {
  // 左侧：一键生成
  rrect(s, 0.55, 1.78, 4.35, 3.1, C.card2, C.line, 0.12);
  txt(s, 0.85, 1.95, 3.7, 0.35, '一键生成模式', { fontSize: 16, bold: true, color: C.accent });
  txt(s, 0.85, 2.38, 3.8, 0.5, '输入主题或上传材料 → 自动规划大纲 → 生成完整课堂', { fontSize: 11.5, color: C.sub });
  const flow = ['输入主题 / 上传材料', '自动规划课程大纲', '生成各场景内容', '组装完整课堂并播放'];
  flow.forEach((f, i) => {
    const fy = 2.95 + i * 0.45;
    ellipse(s, 0.9, fy, 0.2, 0.2, C.accent);
    txt(s, 1.22, fy, 3.4, 0.3, f, { fontSize: 11.5, color: C.ink });
    if (i < 3) line(s, 1.0, fy + 0.18, 1.0, fy + 0.44, C.line, 0.75);
  });

  // 右侧：工作台模式
  rrect(s, 5.1, 1.78, 4.35, 3.1, C.card2, C.line, 0.12);
  txt(s, 5.4, 1.95, 3.7, 0.35, 'Agent 工作台模式（重点）', { fontSize: 15, bold: true, color: C.accent2 });
  const wb = [
    '聊天式交互，与生成 Agent 持续对话',
    '负责课程规划·页面构建·内容修订',
    '支持上传文档/音频/视频/搜索素材',
    '会话可中断、恢复、随时人工干预',
    '内置可扩展 Skills 体系',
  ];
  wb.forEach((w, i) => {
    ellipse(s, 5.42, 2.42 + i * 0.42, 0.18, 0.18, C.accent2);
    txt(s, 5.72, 2.36 + i * 0.42, 3.6, 0.32, w, { fontSize: 11, color: C.sub });
  });
});

// ================= P8 多智能体课堂运行时 =================
page(8, 'RUNTIME', '多智能体课堂运行时', 'AI 教师与 AI 同学同堂互动，沉浸式学习', function (s) {
  // 角色卡
  txt(s, 0.55, 1.72, 8.9, 0.3, '角色设计', { fontSize: 14, bold: true, color: C.ink });
  const roles = [
    ['沈老师', 'AI 教师 · 主讲讲解', C.accent],
    ['林晓', 'AI 同学 · 提问/笔记', C.accent2],
    ['陈默', 'AI 同学 · 补充/辩论', C.accent3],
    ['苏雨', 'AI 同学 · 讨论互动', C.accent],
  ];
  let rx = 0.55;
  roles.forEach((r) => {
    rrect(s, rx, 2.05, 2.02, 1.15, C.card, null, 0.1);
    ellipse(s, rx + 0.24, 2.25, 0.7, 0.7, r[2]);
    txt(s, rx + 0.24, 2.42, 0.7, 0.3, r[0].charAt(0), { fontSize: 18, bold: true, color: C.white, align: 'center' });
    txt(s, rx + 1.05, 2.25, 0.95, 0.3, r[0], { fontSize: 12, bold: true, color: C.ink });
    txt(s, rx + 1.05, 2.55, 0.95, 0.5, r[1], { fontSize: 9.5, color: C.sub, lineSpacingMultiple: 1.15 });
    rx += 2.18;
  });

  // 场景类型
  txt(s, 0.55, 3.4, 8.9, 0.3, '场景类型', { fontSize: 14, bold: true, color: C.ink });
  const scenes = ['幻灯片讲解', '测验与即时反馈', '交互式 HTML 模拟', '项目式学习 PBL', '深度交互（可视化/编程/思维导图）'];
  scenes.forEach((sc, i) => {
    const x = 0.55, y = 3.72 + i * 0.33;
    rrect(s, x, y, 1.75, 0.27, C.card2, C.line, 0.05);
    txt(s, x, y + 0.03, 1.75, 0.22, sc, { fontSize: 10.5, color: C.sub, align: 'center' });
  });
  // 互动能力
  txt(s, 4.6, 3.4, 4, 0.3, '互动能力', { fontSize: 14, bold: true, color: C.ink });
  const inter = ['白板实时板书与绘图', '语音讲解 TTS + 语音输入 ASR', '多轮讨论与实时问答', '沉浸模式与快捷键操作'];
  inter.forEach((it, i) => {
    ellipse(s, 4.6, 3.72 + i * 0.42, 0.18, 0.18, C.accent3);
    txt(s, 4.9, 3.66 + i * 0.42, 4.4, 0.32, it, { fontSize: 11.5, color: C.sub });
  });
});

// ================= P9 编辑与导出 =================
page(9, 'CREATE & EXPORT', '编辑与导出模块', '可视化编辑 + AI 辅助修改 + 多格式导出', function (s) {
  // 左：编辑器
  rrect(s, 0.55, 1.78, 4.35, 2.9, C.card2, C.line, 0.12);
  txt(s, 0.85, 1.95, 3.7, 0.35, '可视化幻灯片编辑器', { fontSize: 15, bold: true, color: C.accent });
  const eds = ['拖拽 / 缩放 / 旋转', '多选与分组编辑', '历史回退与撤销', '属性面板实时调整'];
  eds.forEach((e, i) => {
    ellipse(s, 0.9, 2.45 + i * 0.43, 0.18, 0.18, C.accent);
    txt(s, 1.22, 2.4 + i * 0.43, 3.4, 0.32, e, { fontSize: 11.5, color: C.sub });
  });
  txt(s, 0.85, 4.22, 3.7, 0.35, 'AI 辅助编辑', { fontSize: 13, bold: true, color: C.accent2 });
  txt(s, 0.85, 4.58, 3.7, 0.4, '通过自然语言指令修改已有内容，无需专业设计技能。', { fontSize: 11, color: C.sub });

  // 右：导出
  rrect(s, 5.1, 1.78, 4.35, 2.9, C.card2, C.line, 0.12);
  txt(s, 5.4, 1.95, 3.7, 0.35, '导出能力', { fontSize: 15, bold: true, color: C.accent2 });
  const exports = [
    ['可编辑 PPTX', '无缝接入 Office 生态', C.accent],
    ['交互式 HTML', '支持离线，随时分享', C.accent2],
    ['课程视频 MP4', '完整授课过程回放', C.accent3],
    ['PDF 讲义', '清爽排版便于打印', C.accent],
  ];
  exports.forEach((e, i) => {
    const ey = 2.45 + i * 0.55;
    rrect(s, 5.4, ey, 3.85, 0.44, C.card, null, 0.08);
    txt(s, 5.55, ey + 0.04, 1.7, 0.32, e[0], { fontSize: 11.5, bold: true, color: e[2] });
    txt(s, 7.3, ey + 0.06, 1.9, 0.32, e[1], { fontSize: 9.5, color: C.sub });
  });
});

// ================= P10 能力抽象层与材料处理 =================
page(10, 'PROVIDER', '能力抽象层与材料处理', 'Provider 中立，灵活替换，避免强绑定单一厂商', function (s) {
  // 能力抽象
  txt(s, 0.55, 1.72, 8.9, 0.3, '能力抽象层（Provider 中立）', { fontSize: 14, bold: true, color: C.ink });
  const caps = [
    ['大语言模型', '云端 / 本地均可接入', C.accent],
    ['语音合成与识别', 'TTS / ASR 可插拔替换', C.accent2],
    ['图像与视频生成', '封面、示意图、短片', C.accent3],
    ['文档解析', '多格式 + 音视频抽取', C.accent],
    ['网络搜索', '实时补充最新知识', C.accent2],
  ];
  let cx = 0.55;
  caps.forEach((cap) => {
    rrect(s, cx, 2.12, 1.66, 1.4, C.card2, C.line, 0.1);
    ellipse(s, cx + 0.68, 2.28, 0.3, 0.3, cap[2]);
    txt(s, cx + 0.12, 2.68, 1.42, 0.4, cap[0], { fontSize: 11.5, bold: true, color: C.ink, align: 'center' });
    txt(s, cx + 0.12, 3.05, 1.42, 0.4, cap[1], { fontSize: 9.5, color: C.sub, align: 'center' });
    cx += 1.8;
  });

  // 材料处理
  txt(s, 0.55, 3.7, 8.9, 0.3, '材料与知识处理', { fontSize: 14, bold: true, color: C.ink });
  const mats = ['上传文档/音频/视频', '自动解析·切分·提炼', '作为生成上下文材料', '向量检索增强长材料利用'];
  let mx = 0.55;
  mats.forEach((m) => {
    rrect(s, mx, 4.05, 2.02, 0.85, C.card, null, 0.1);
    txt(s, mx + 0.2, 4.22, 1.7, 0.5, m, { fontSize: 10.5, color: C.sub, align: 'center', lineSpacingMultiple: 1.2 });
    mx += 2.18;
  });
  txt(s, 0.55, 5.0, 8.9, 0.3, '启动时进行能力校验，失败时给出明确提示，避免运行时中断。', { fontSize: 11, bold: true, color: C.accent, align: 'center' });
});

// ================= P11 数据与状态设计 =================
page(11, 'DATA', '数据与状态设计', '以课程 DSL 为核心，会话与资产统一管理', function (s) {
  // 左：核心数据模型
  rrect(s, 0.55, 1.78, 4.35, 3.1, C.card2, C.line, 0.12);
  txt(s, 0.85, 1.95, 3.7, 0.35, '核心数据模型', { fontSize: 15, bold: true, color: C.accent });
  const models = [
    ['课程文档', '内部 DSL 描述场景结构（页面、元素、测验、交互、时间线）'],
    ['会话状态', '生成中间状态、消息历史、材料引用，支持持久化恢复'],
    ['资产库', '图片、音频、视频统一注册与管理'],
    ['用户进度', '测验答题状态、课程完成情况'],
  ];
  models.forEach((m, i) => {
    ellipse(s, 0.9, 2.4 + i * 0.62, 0.18, 0.18, C.accent);
    txt(s, 0.9, 2.62 + i * 0.62, 0.9, 0.2, m[0], { fontSize: 11, bold: true, color: C.ink });
    txt(s, 1.85, 2.35 + i * 0.62, 3.0, 0.5, m[1], { fontSize: 10.5, color: C.sub, lineSpacingMultiple: 1.2 });
  });

  // 右：持久化策略
  rrect(s, 5.1, 1.78, 4.35, 2.0, C.card2, C.line, 0.12);
  txt(s, 5.4, 1.95, 3.7, 0.35, '持久化策略', { fontSize: 15, bold: true, color: C.accent2 });
  const pers = [
    ['开发阶段', '本地存储 或 SQLite'],
    ['生产环境', 'PostgreSQL + 对象存储'],
    ['能力增强', '支持增量保存与会话回放'],
  ];
  pers.forEach((p, i) => {
    rrect(s, 5.4, 2.35 + i * 0.45, 3.85, 0.36, C.card, null, 0.07);
    txt(s, 5.55, 2.4 + i * 0.45, 1.3, 0.3, p[0], { fontSize: 11, bold: true, color: C.ink });
    txt(s, 6.95, 2.41 + i * 0.45, 2.2, 0.28, p[1], { fontSize: 10, color: C.sub });
  });
  txt(s, 5.4, 3.95, 3.7, 0.7, '课程 DSL 是整堂课唯一数据源，生成、编辑、播放、导出都围绕它进行。', { fontSize: 11, color: C.sub, lineSpacingMultiple: 1.35 });
});

// ================= P12 关键流程设计 =================
page(12, 'WORKFLOW', '关键流程设计', '一键生成、工作台编排、课堂运行三条主线', function (s) {
  // 三列流程
  const flows = [
    { t: '一键生成流程', c: C.accent,
      steps: ['输入主题或上传材料', '大纲 Agent 生成课程结构', '用户确认或微调大纲', '并行生成各场景内容', '组装课堂并进入播放器'] },
    { t: 'Agent 工作台流程', c: C.accent2,
      steps: ['进入聊天工作区', '上传材料或描述需求', 'Agent 规划 + 调用 Skills 生成', '随时打断、修改或直接编辑', '确认并保存/导出'] },
    { t: '课堂运行流程', c: C.accent3,
      steps: ['加载课程 DSL', '按时间线驱动讲解与白板', '触发测验/交互时暂停等待', 'AI 同学插入讨论或提问', '记录进度支持断点续学'] },
  ];
  let fx = 0.55;
  flows.forEach((fl) => {
    rrect(s, fx, 1.78, 2.9, 3.3, C.card2, C.line, 0.12);
    rect(s, fx, 1.78, 2.9, 0.5, fl.c);
    txt(s, fx + 0.2, 1.85, 2.5, 0.34, fl.t, { fontSize: 13, bold: true, color: C.white });
    fl.steps.forEach((st, i) => {
      const sy = 2.45 + i * 0.48;
      ellipse(s, fx + 0.22, sy, 0.26, 0.26, fl.c);
      txt(s, fx + 0.2, sy + 0.02, 0.26, 0.22, String(i + 1), { fontSize: 10, bold: true, color: C.white, align: 'center' });
      txt(s, fx + 0.6, sy, 2.2, 0.4, st, { fontSize: 10.5, color: C.sub, lineSpacingMultiple: 1.15 });
    });
    fx += 3.02;
  });
});

// ================= P13 技术栈 =================
page(13, 'TECH STACK', '推荐技术栈', '面向可扩展性与本地/云端混合部署的现代技术选型', function (s) {
  // 左侧 tech grid
  const techs = [
    ['前端', 'Next.js · React · TypeScript · Tailwind CSS', C.accent],
    ['智能体编排', 'LangGraph 状态机框架', C.accent2],
    ['后端服务', 'Next.js API Routes 或独立 FastAPI', C.accent3],
    ['数据库', 'PostgreSQL 会话与课程持久化', C.accent],
    ['向量/文档', '可选轻量向量库辅助材料检索', C.accent2],
    ['部署', 'Docker Compose / 云平台', C.accent3],
  ];
  let idx = 0;
  techs.forEach((t) => {
    const col = idx % 2, row = Math.floor(idx / 2);
    const gx = 0.55 + col * 4.48, gy = 1.75 + row * 0.72;
    rrect(s, gx, gy, 4.3, 0.6, C.card2, C.line, 0.08);
    chip(s, gx + 0.16, gy + 0.13, 1.35, t[0], C.card, t[2]);
    txt(s, gx + 1.6, gy + 0.14, 2.6, 0.36, t[1], { fontSize: 10.5, color: C.sub });
    idx++;
  });

  // 右侧总结
  rrect(s, 0.55, 3.75, 8.9, 1.4, C.card, null, 0.12);
  txt(s, 0.85, 3.9, 8.3, 0.3, '技术选型原则', { fontSize: 13, bold: true, color: C.accent });
  txt(s, 0.85, 4.24, 8.3, 0.9,
    '· 状态机编排让多智能体协作可追踪、可控\n· 前端采用现代技术栈保障交互体验与编辑器性能\n· 后端能力中立，云端/本地混合部署灵活',
    { fontSize: 11.5, color: C.sub, lineSpacingMultiple: 1.5 });
});

// ================= P14 安全与工程化 =================
page(14, 'SECURITY', '安全与工程化设计', '保障安全、可观测、可运维的工程实践', function (s) {
  const secs = [
    ['接口鉴权', '可选站点访问码，防止未授权访问', C.accent],
    ['SSRF 防护', '外部请求白名单 + 校验，杜绝内网探测', C.accent2],
    ['交互沙箱', '交互组件隔离运行，防止越权执行', C.accent3],
    ['内容安全', '可选内容过滤，保障课堂内容合规', C.accent],
  ];
  let sx = 0.55;
  secs.forEach((sec, i) => {
    const x = 0.55 + (i % 2) * 4.48, y = 1.75 + Math.floor(i / 2) * 1.2;
    rrect(s, x, y, 4.3, 1.05, C.card2, C.line, 0.1);
    ellipse(s, x + 0.22, y + 0.32, 0.36, 0.36, sec[2]);
    txt(s, x + 0.72, y + 0.22, 1.4, 0.3, sec[0], { fontSize: 13, bold: true, color: C.ink });
    txt(s, x + 0.22, y + 0.72, 3.9, 0.3, sec[1], { fontSize: 10, color: C.sub });
  });

  txt(s, 0.55, 4.15, 8.9, 0.3, '工程化实践', { fontSize: 13, bold: true, color: C.ink });
  const engs = ['完整日志与错误可观测', '单元测试 + 端到端测试', 'Docker 一键部署 + 环境变量配置'];
  engs.forEach((e, i) => {
    const ex = 0.55 + i * 3.05;
    rrect(s, ex, 4.5, 2.85, 0.62, C.card, null, 0.08);
    txt(s, ex + 0.2, 4.62, 2.5, 0.4, e, { fontSize: 11, color: C.sub, align: 'center', lineSpacingMultiple: 1.1 });
  });
});

// ================= P15 路线与成果 =================
page(15, 'ROADMAP', '实施路线与预期成果', '分阶段推进，逐步完善 Skills 体系与深度交互', function (s) {
  // 三阶段
  const stages = [
    { t: '第一阶段 · MVP', d: '一键主题生成（幻灯片+测验）\n基础多智能体讲解与 TTS\n简单 Web 播放器\n本地或单一大模型接入', c: C.accent },
    { t: '第二阶段 · 工作台', d: 'Agent 工作台与会话持久化\n材料上传与解析\n白板 + 基础交互场景\nPPTX / HTML 导出', c: C.accent2 },
    { t: '第三阶段 · 完整生态', d: '完整 Skills 体系\n深度交互与 PBL\n视频导出\n多 Provider 与编辑器增强', c: C.accent3 },
  ];
  let sx = 0.55;
  stages.forEach((st) => {
    rrect(s, sx, 1.75, 2.9, 2.35, C.card2, C.line, 0.12);
    rect(s, sx, 1.75, 2.9, 0.52, st.c);
    txt(s, sx + 0.2, 1.82, 2.5, 0.36, st.t, { fontSize: 12.5, bold: true, color: C.white });
    txt(s, sx + 0.2, 2.4, 2.55, 1.6, st.d, { fontSize: 10.5, color: C.sub, lineSpacingMultiple: 1.5, valign: 'top' });
    sx += 3.02;
  });

  // 预期成果
  txt(s, 0.55, 4.3, 8.9, 0.3, '预期成果', { fontSize: 13, bold: true, color: C.ink });
  const outs = ['完整可运行系统原型', '清晰课程 DSL 与编排设计', '一键生成 + 可干预工作台', '可导出课堂产物', '完整设计文档与部署说明'];
  outs.forEach((o, i) => {
    const ox = 0.55 + i * 1.78;
    rrect(s, ox, 4.62, 1.7, 0.62, C.card, null, 0.08);
    txt(s, ox + 0.1, 4.7, 1.55, 0.48, o, { fontSize: 9, color: C.sub, align: 'center', lineSpacingMultiple: 1.1 });
  });
});

// ================= SAVE =================
pptx.writeFile({ fileName: 'EduAgentX_项目说明.pptx' }).then((fn) => {
  console.log('SAVED:', fn);
}).catch((e) => { console.error('ERR', e); });

module.exports = { pptx, C, F, S };
