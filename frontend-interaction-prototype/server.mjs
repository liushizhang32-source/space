import http from 'node:http';
import { createReadStream } from 'node:fs';
import { stat } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
const root = path.dirname(fileURLToPath(import.meta.url));
const files = {'/':['index.html','text/html; charset=utf-8'],'/index.html':['index.html','text/html; charset=utf-8'],'/app.js':['app.js','text/javascript; charset=utf-8'],'/style.css':['style.css','text/css; charset=utf-8']};
http.createServer(async (req,res)=>{
  const entry=files[new URL(req.url,'http://localhost').pathname];
  if(!entry||!['GET','HEAD'].includes(req.method)){res.writeHead(404);res.end();return;}
  try{const filename=path.join(root,entry[0]);const size=(await stat(filename)).size;const headers={'content-type':entry[1],'accept-ranges':'bytes','cache-control':'no-store'};let start=0,end=size-1,status=200;
    if(req.headers.range){const match=/^bytes=(\d*)-(\d*)$/.exec(req.headers.range);if(!match||(!match[1]&&!match[2])){res.writeHead(416,{'content-range':`bytes */${size}`});res.end();return;}if(match[1]){start=Number(match[1]);end=match[2]?Number(match[2]):end;}else{const count=Number(match[2]);start=Math.max(size-count,0);}if(start>=size||end<start){res.writeHead(416,{'content-range':`bytes */${size}`});res.end();return;}end=Math.min(end,size-1);status=206;headers['content-range']=`bytes ${start}-${end}/${size}`;}
    headers['content-length']=end-start+1;res.writeHead(status,headers);if(req.method==='HEAD'){res.end();return;}createReadStream(filename,{start,end}).pipe(res);
  }catch{if(!res.headersSent)res.writeHead(500);res.end();}
}).listen(5194,'127.0.0.1',()=>console.log('http://127.0.0.1:5194/'));
