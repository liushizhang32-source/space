import http from 'node:http';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const dir = path.dirname(fileURLToPath(import.meta.url));
const target = new URL(process.env.BACKEND_URL || 'http://127.0.0.1:8000');
const port = Number(process.env.PORT || 5173);
const assets = new Set(['/api', '/previews', '/json', '/audios', '/videos']);
const files = { '/': ['index.html', 'text/html; charset=utf-8'], '/app.js': ['app.js', 'text/javascript; charset=utf-8'], '/style.css': ['style.css', 'text/css; charset=utf-8'] };

http.createServer(async (req, res) => {
  const pathname = new URL(req.url, 'http://localhost').pathname;
  if ([...assets].some(p => pathname === p || pathname.startsWith(p + '/'))) {
    const proxy = http.request(new URL(req.url, target), { method: req.method, headers: { ...req.headers, host: target.host } }, upstream => {
      res.writeHead(upstream.statusCode, upstream.headers);
      upstream.pipe(res);
    });
    proxy.on('error', () => { if (!res.headersSent) res.writeHead(502, { 'content-type': 'text/plain; charset=utf-8' }); res.end('后端连接失败，请确认 Mock 服务已启动。'); });
    req.pipe(proxy);
    return;
  }
  if (!files[pathname] || !['GET', 'HEAD'].includes(req.method)) { res.writeHead(404); res.end(); return; }
  try { const [file, type] = files[pathname]; const data = await readFile(path.join(dir, file)); res.writeHead(200, { 'content-type': type, 'cache-control': 'no-store' }); res.end(req.method === 'HEAD' ? undefined : data); }
  catch { res.writeHead(500); res.end(); }
}).listen(port, '127.0.0.1', () => console.log(`纸书智伴前端：http://127.0.0.1:${port}`));
