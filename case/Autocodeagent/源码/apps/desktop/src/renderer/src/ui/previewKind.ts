/**
 * 预览格式识别与产出路径提取（右栏「预览」Tab / 回合结束自动弹出共用）。
 * previewKind：按扩展名分流渲染；extractPreviewPaths：从助手消息正文识别产出文件路径。
 */
export type PreviewKind = 'html' | 'markdown' | 'image' | 'docx' | 'pdf';

const KIND_BY_EXT: Record<string, PreviewKind> = {
  html: 'html',
  htm: 'html',
  md: 'markdown',
  markdown: 'markdown',
  svg: 'image',
  png: 'image',
  jpg: 'image',
  jpeg: 'image',
  gif: 'image',
  webp: 'image',
  docx: 'docx',
  pdf: 'pdf',
};

/** 可预览扩展名（正则源，与 KIND_BY_EXT 同源） */
const EXT_SOURCE = 'html|htm|md|markdown|svg|png|jpe?g|gif|webp|docx|pdf';

export function previewKind(path: string): PreviewKind | null {
  const m = /\.([a-z0-9]+)$/i.exec(path);
  if (!m) return null;
  return KIND_BY_EXT[m[1]!.toLowerCase()] ?? null;
}

/**
 * 从助手消息正文提取预览类产出文件路径（去重保序）。
 * 启发式：捕获以预览扩展名结尾的非空白 token，再归一化——
 * 含盘符则从盘符截起（去掉「交付文件：」等前导标签）；否则去掉到首个冒号为止的前导标签；最后去尾随标点。
 */
export function extractPreviewPaths(text: string): string[] {
  const out: string[] = [];
  const re = new RegExp(`[^\\s\`"'<>|]*\\.(?:${EXT_SOURCE})\\b`, 'gi');
  for (const m of text.matchAll(re)) {
    let p = m[0];
    const drive = /[A-Za-z]:[\\/]/.exec(p);
    if (drive) p = p.slice(drive.index);
    else p = p.replace(/^[^:：]*[:：]/, '');
    p = p.replace(/[),.;:，。；：、]+$/, '');
    if (p && previewKind(p) !== null && !out.includes(p)) out.push(p);
  }
  return out;
}
