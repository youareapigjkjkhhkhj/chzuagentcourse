/**
 * 测试夹具：真实 MCP stdio server（官方 SDK server 端）。
 * 提供 4 个工具：ping 回显 / envprobe 探环境变量注入 / failing 返回 isError / crash 模拟进程崩溃。
 */
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { ListToolsRequestSchema, CallToolRequestSchema } from '@modelcontextprotocol/sdk/types.js';

const server = new Server({ name: 'echo', version: '0.0.1' }, { capabilities: { tools: {} } });

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: 'ping',
      description: '回显输入文本（echo 连接器）',
      inputSchema: { type: 'object', properties: { text: { type: 'string' } }, required: ['text'] },
    },
    { name: 'envprobe', description: '返回 ECHO_PROBE 环境变量的值', inputSchema: { type: 'object', properties: {} } },
    { name: 'failing', description: '总是返回错误结果', inputSchema: { type: 'object', properties: {} } },
    { name: 'crash', description: '退出进程（模拟崩溃）', inputSchema: { type: 'object', properties: {} } },
  ],
}));

server.setRequestHandler(CallToolRequestSchema, async (req) => {
  const args = req.params.arguments ?? {};
  switch (req.params.name) {
    case 'ping':
      return { content: [{ type: 'text', text: `pong: ${String(args['text'] ?? '')}` }] };
    case 'envprobe':
      return { content: [{ type: 'text', text: process.env['ECHO_PROBE'] ?? '' }] };
    case 'failing':
      return { content: [{ type: 'text', text: '工具报告了错误' }], isError: true };
    case 'crash':
      // 延迟退出：让本次调用结果先回传，随后管道断开触发客户端 onclose
      setTimeout(() => process.exit(3), 30);
      return { content: [{ type: 'text', text: '即将崩溃' }] };
    default:
      return { content: [{ type: 'text', text: '未知工具' }], isError: true };
  }
});

await server.connect(new StdioServerTransport());
