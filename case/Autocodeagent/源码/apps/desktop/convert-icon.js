import sharp from 'sharp';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

async function convert() {
    const inputPath = path.join(__dirname, 'build', 'logo.png');
    const outputPath = path.join(__dirname, 'build', 'icon.ico');
    
    // 生成多种尺寸的 PNG
    const sizes = [16, 32, 48, 64, 128, 256];
    const buffers = [];
    
    for (const size of sizes) {
        const buffer = await sharp(inputPath)
            .resize(size, size)
            .png()
            .toBuffer();
        buffers.push(buffer);
    }
    
    // 创建 ICO 文件（简化版，使用最大尺寸）
    const icoHeader = Buffer.alloc(6);
    icoHeader.writeUInt16LE(0, 0); // 保留
    icoHeader.writeUInt16LE(1, 2); // 类型：图标
    icoHeader.writeUInt16LE(1, 4); // 图片数量
    
    // ICO 目录条目
    const icoEntry = Buffer.alloc(16);
    icoEntry.writeUInt8(0, 0); // 宽度（0 = 256）
    icoEntry.writeUInt8(0, 1); // 高度（0 = 256）
    icoEntry.writeUInt8(0, 2); // 颜色表
    icoEntry.writeUInt8(0, 3); // 保留
    icoEntry.writeUInt16LE(1, 4); // 颜色平面
    icoEntry.writeUInt16LE(32, 6); // 每像素位数
    icoEntry.writeUInt32LE(buffers[5].length, 8); // 图片大小
    icoEntry.writeUInt32LE(22, 12); // 图片偏移
    
    // 组装 ICO 文件
    const ico = Buffer.concat([icoHeader, icoEntry, buffers[5]]);
    fs.writeFileSync(outputPath, ico);
    
    console.log('Icon created:', outputPath);
}

convert().catch(console.error);
