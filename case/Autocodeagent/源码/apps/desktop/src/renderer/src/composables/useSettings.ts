/**
 * P3 应用设置共享状态（模块级单例）：
 * 顶栏状态 chip 与输入框盾牌弹层同源，切换后两处即时同步，无需事件广播。
 */
import { ref } from 'vue';
import type { PermissionMode } from '@agentbuddy/shared';
import { agent } from '../api/bridge';

const permMode = ref<PermissionMode>('Ask');

export function useSettings() {
  /** 挂载时读取持久化设置（config.json） */
  async function loadSettings(): Promise<void> {
    const s = await agent().config.getSettings();
    if (s.ok && s.data) permMode.value = s.data.permissionMode;
  }

  /** 切换模式并持久化；成功返回 null，失败返回错误信息 */
  async function setMode(mode: PermissionMode): Promise<string | null> {
    const res = await agent().config.setSettings({ permissionMode: mode });
    if (res.ok && res.data) {
      permMode.value = res.data.permissionMode;
      return null;
    }
    return res.error ?? '切换权限模式失败';
  }

  return { permMode, loadSettings, setMode };
}
