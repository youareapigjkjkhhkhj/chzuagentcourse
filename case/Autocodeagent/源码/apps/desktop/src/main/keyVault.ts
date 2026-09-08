/**
 * API Key 密文 vault（P6 任务 1）：Electron safeStorage 实现（OS 级加密，~/.AgentBuddy/keys.json 仅存密文）。
 * 加密不可用的极端环境回退 base64 混淆（仍保证磁盘无明文）。
 * `models.setKey` 只在 Main 完成；Renderer 仅见掩码。
 */
import { safeStorage } from 'electron';
import type { SecretVault } from '@agent-core/agent-core';

export function createKeyVault(): SecretVault {
  if (safeStorage.isEncryptionAvailable()) {
    return {
      encrypt: (plain) => `ss1:${safeStorage.encryptString(plain).toString('base64')}`,
      decrypt: (token) =>
        token.startsWith('ss1:') ? safeStorage.decryptString(Buffer.from(token.slice(4), 'base64')) : '',
    };
  }
  return {
    encrypt: (plain) => `obf1:${Buffer.from(plain, 'utf-8').toString('base64')}`,
    decrypt: (token) =>
      token.startsWith('obf1:') ? Buffer.from(token.slice(5), 'base64').toString('utf-8') : '',
  };
}
