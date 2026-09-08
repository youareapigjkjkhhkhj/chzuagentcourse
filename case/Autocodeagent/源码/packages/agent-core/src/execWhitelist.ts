/**
 * Auto 模式 EXEC 低风险白名单（P3 任务 4，§4.2）。
 * 定位为启发式便利清单而非安全边界：真正边界仍是 Permission Gate + workspace jail。
 * 可通过 settings.execWhitelist（正则源串数组）整体替换；空数组 = 内置默认。
 */

/** 内置默认清单：ls / pwd / echo / cat / git 只读 / 版本查询 / npm test / npm run test|build */
export const DEFAULT_EXEC_WHITELIST: string[] = [
  '^ls(\\s+.*)?$',
  '^pwd$',
  '^echo\\b',
  '^cat\\s+\\S',
  '^git\\s+(status|log|diff|branch|show)(\\s+.*)?$',
  '^npm\\s+(-v|--version)$',
  '^node\\s+(-v|--version)$',
  '^npm\\s+test(\\s+.*)?$',
  '^npm\\s+run\\s+(test|build)(\\s+.*)?$',
];

/** 复合命令特征：含连接符/管道/换行/反引号一律不走白名单，防 `npm test && rm -rf` 夹带 */
const COMPOUND = /(&&|\|\||[;|]|\n|`|\$\()/;

/** 编译白名单为匹配器；非法正则静默忽略（配置容错），空/缺省回退内置默认 */
export function compileWhitelist(patterns?: string[]): (command: string) => boolean {
  const sources = patterns && patterns.length > 0 ? patterns : DEFAULT_EXEC_WHITELIST;
  const regexes: RegExp[] = [];
  for (const src of sources) {
    try {
      regexes.push(new RegExp(src, 'i'));
    } catch {
      // 非法正则跳过，不让配置错误击穿整条白名单
    }
  }
  return (command: string) => {
    const cmd = command.trim();
    if (!cmd || COMPOUND.test(cmd)) return false;
    return regexes.some((re) => re.test(cmd));
  };
}
