/**
 * 极简 ZIP 解析（零第三方依赖）：从尾部 EOCD 定位中央目录，逐条读局部头取数据；
 * 仅支持 stored(0) 与 deflate(8)，带体积上限防 zip 炸弹。
 * 技能导入只认 SKILL.md 条目，技能名取 frontmatter（slug 校验），不使用条目路径，天然防 zip-slip。
 */
import { inflateRawSync } from 'node:zlib';

const EOCD_SIG = 0x06054b50;
const CD_SIG = 0x02014b50;
const LOCAL_SIG = 0x04034b50;

/** 解包体积护栏：单条目 ≤ 1MB，总量 ≤ 8MB，条目数 ≤ 200 */
const MAX_ENTRY_BYTES = 1024 * 1024;
const MAX_TOTAL_BYTES = 8 * 1024 * 1024;
const MAX_ENTRIES = 200;

export interface ZipEntry {
  name: string;
  data: Buffer;
}

/** CP437 高半区码表（0x80-0xFF）；未置 UTF-8 标志位的老 ZIP（如 Windows Compress-Archive）用此解码文件名 */
const CP437_HIGH =
  'ÇüéâäàåçêëèïîìÄÅÉæÆôöòûùÿÖÜ¢£¥₧ƒáíóúñÑªº¿⌐¬½¼¡«»░▒▓│┤╡╢╖╕╣║╗╝╜╛┐└┴┬├─┼╞╟╚╔╩╦╠═╬╧╨╤╥╙╘╒╓╫╪┘┌█▄▌▐▀αβΓπΣσµτΦΘΩδ∞φε∩≡±≥≤⌠⌡÷≈°∙·√ⁿ²■ ';

/** 文件名解码：UTF-8 标志位（bit 11）置位按 UTF-8，否则按 CP437；输出统一为正斜杠路径 */
function decodeName(buf: Buffer, flags: number): string {
  const raw = flags & 0x0800 ? buf.toString('utf-8') : [...buf].map((b) => (b < 0x80 ? String.fromCharCode(b) : CP437_HIGH[b - 0x80] ?? '?')).join('');
  return raw.replace(/\\/g, '/');
}

/** 从尾部向前找 EOCD（注释最长 65535 字节） */
function findEocd(buf: Buffer): number {
  const min = Math.max(0, buf.length - 22 - 65535);
  for (let i = buf.length - 22; i >= min; i--) {
    if (buf.readUInt32LE(i) === EOCD_SIG) return i;
  }
  return -1;
}

export function parseZip(buf: Buffer): ZipEntry[] {
  const eocd = findEocd(buf);
  if (eocd < 0) throw new Error('非法 ZIP：未找到目录结束标记');
  const count = buf.readUInt16LE(eocd + 10);
  const cdOffset = buf.readUInt32LE(eocd + 16);
  if (count > MAX_ENTRIES) throw new Error(`ZIP 条目过多（上限 ${MAX_ENTRIES}）`);

  const entries: ZipEntry[] = [];
  let total = 0;
  let p = cdOffset;
  for (let i = 0; i < count; i++) {
    if (p + 46 > buf.length || buf.readUInt32LE(p) !== CD_SIG) throw new Error('非法 ZIP：中央目录损坏');
    const method = buf.readUInt16LE(p + 10);
    const flags = buf.readUInt16LE(p + 8);
    const compSize = buf.readUInt32LE(p + 20);
    const nameLen = buf.readUInt16LE(p + 28);
    const extraLen = buf.readUInt16LE(p + 30);
    const commentLen = buf.readUInt16LE(p + 32);
    const localOffset = buf.readUInt32LE(p + 42);
    const name = decodeName(buf.subarray(p + 46, p + 46 + nameLen), flags);
    p += 46 + nameLen + extraLen + commentLen;

    if (name.endsWith('/')) continue; // 目录条目无数据
    if (localOffset + 30 > buf.length || buf.readUInt32LE(localOffset) !== LOCAL_SIG) {
      throw new Error('非法 ZIP：局部头损坏');
    }
    const lNameLen = buf.readUInt16LE(localOffset + 26);
    const lExtraLen = buf.readUInt16LE(localOffset + 28);
    const dataStart = localOffset + 30 + lNameLen + lExtraLen;
    if (dataStart + compSize > buf.length) throw new Error('非法 ZIP：数据越界');
    const raw = buf.subarray(dataStart, dataStart + compSize);

    let data: Buffer;
    if (method === 0) data = Buffer.from(raw);
    else if (method === 8) data = inflateRawSync(raw);
    else throw new Error(`不支持的压缩方式：${name}`);

    if (data.length > MAX_ENTRY_BYTES) throw new Error(`条目过大（上限 1MB）：${name}`);
    total += data.length;
    if (total > MAX_TOTAL_BYTES) throw new Error('解包总量超限（8MB）');
    entries.push({ name, data });
  }
  return entries;
}
