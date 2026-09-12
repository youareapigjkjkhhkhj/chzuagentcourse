/** ripgrep 纯解析函数单测：验证 --json / --files 输出解析、相对化、上限截断与残行容错（无需真实 rg） */
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { parseRgFileList, parseRgJson } from '../src/tools/ripgrep';

const ROOT = join(process.cwd(), 'ws-root');

function abs(...parts: string[]): string {
  return join(ROOT, ...parts);
}

describe('parseRgJson', () => {
  it('仅取 match 事件，输出「相对路径:行号: 内容」并去掉行尾换行', () => {
    const out = [
      JSON.stringify({ type: 'begin', data: { path: { text: abs('src', 'a.ts') } } }),
      JSON.stringify({
        type: 'match',
        data: { path: { text: abs('src', 'a.ts') }, line_number: 3, lines: { text: 'const x = 1;\n' } },
      }),
      JSON.stringify({ type: 'end', data: { path: { text: abs('src', 'a.ts') } } }),
    ].join('\n');
    expect(parseRgJson(out, ROOT, 200)).toEqual(['src/a.ts:3: const x = 1;']);
  });

  it('达到 max 上限即停止解析', () => {
    const rows = [1, 2, 3].map((n) =>
      JSON.stringify({
        type: 'match',
        data: { path: { text: abs('b.ts') }, line_number: n, lines: { text: `line ${n}\n` } },
      }),
    );
    const parsed = parseRgJson(rows.join('\n'), ROOT, 2);
    expect(parsed).toHaveLength(2);
    expect(parsed[0]).toBe('b.ts:1: line 1');
  });

  it('跳过无法解析的残行与缺 path 的事件，不抛错', () => {
    const out = [
      '{ this is not json',
      '',
      JSON.stringify({ type: 'match', data: { line_number: 9, lines: { text: 'no path\n' } } }),
      JSON.stringify({ type: 'match', data: { path: { text: abs('ok.ts') }, line_number: 1, lines: { text: 'hit\r\n' } } }),
    ].join('\n');
    expect(parseRgJson(out, ROOT, 200)).toEqual(['ok.ts:1: hit']);
  });
});

describe('parseRgFileList', () => {
  it('每行绝对路径相对化到 root（正斜杠），并截断到 max', () => {
    const out = [abs('src', 'a.ts'), abs('src', 'b.ts'), abs('c.ts')].join('\n');
    expect(parseRgFileList(out, ROOT, 2)).toEqual(['src/a.ts', 'src/b.ts']);
  });

  it('忽略空行并去掉尾随 CR', () => {
    const out = `${abs('x.ts')}\r\n\n`;
    expect(parseRgFileList(out, ROOT, 10)).toEqual(['x.ts']);
  });
});
