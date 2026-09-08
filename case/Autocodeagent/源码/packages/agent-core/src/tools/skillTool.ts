/**
 * use_skill 工具（主流 Agent 同款「技能自取」）：
 * 模型按系统提示④层技能目录自主判断，任务匹配某技能描述时主动调用本工具加载正文并严格遵循；
 * 正文以 tool 结果进上下文（渐进披露，不预注入系统提示），与用户手动 /name 触发互补。
 * 风险 READ（只读技能资产，无需权限确认）；专家绑定清单在构造时收口为硬边界（§14）。
 */
import type { SkillHub } from '../skills';
import type { Tool } from './types';
import { str } from './types';

export const SKILL_TOOL_NAME = 'use_skill';

/**
 * 构造技能加载工具。
 * @param hub 技能仓库（两级扫描 / 启停状态同源管理页）
 * @param allowed 专家绑定清单；缺省/空 = 不限定（与④层目录过滤同源）
 */
export function createSkillTool(hub: SkillHub, allowed?: string[]): Tool {
  return {
    name: SKILL_TOOL_NAME,
    description:
      '加载指定技能的正文指令。当任务与系统提示「可用技能」目录中某技能的描述匹配时，主动调用本工具（name=技能名，不含 / 前缀）；返回正文后严格按正文执行本次任务，不要凭印象省略步骤。',
    parameters: {
      type: 'object',
      properties: {
        name: { type: 'string', description: '技能名（不含 / 前缀），取自系统提示「可用技能」目录' },
      },
      required: ['name'],
    },
    risk: 'READ',
    async execute(_ctx, input) {
      const name = str(input, 'name').replace(/^\//, '').trim();
      if (!name) throw new Error('参数 name 不能为空');
      if (allowed && allowed.length > 0 && !allowed.includes(name)) {
        throw new Error(`技能 /${name} 未绑定给当前专家，可用：${allowed.map((n) => `/${n}`).join('、')}`);
      }
      const found = await hub.get(name);
      if (!found) throw new Error(`技能不存在: /${name}（可用技能见系统提示「可用技能」目录）`);
      if (!found.meta.enabled) throw new Error(`技能已禁用: /${name}（可在技能页启用后再调用）`);
      return { text: found.body };
    },
  };
}
