const $ = id => document.getElementById(id);
const ui = Object.fromEntries(['file','previewWrap','preview','pageInfo','pageNo','age','upload','generate','empty','progressArea','status','percent','barFill','stage','stages','stop','resume','videoArea','video','message','diagnostics','diagnosticText'].map(id => [id, $(id)]));
const stageNames = {ocr:'文字识别',vlm:'画面理解',story:'故事生成',tts:'语音合成',render:'视频合成'};
const stageStates = {ok:'完成',empty:'完成（无识别内容）',failed:'失败',skipped:'跳过',running:'进行中',pending:'等待中'};
const jobStates = {queued:'排队中',running:'正在生成',done:'生成完成',failed:'生成失败',cancelled:'任务已取消',partial_failed:'部分生成完成'};
const terminals = new Set(['done','failed','cancelled','partial_failed']);
let selected = null, capture = null, jobId = null, pollController = null, uploadController = null, busy = false, lastTrace = '', lastApi = '', lastCode = '', version = 0;

function showMessage(text, api = '', code = '', trace = '') {
  ui.message.hidden = !text; ui.message.textContent = text || '';
  if (api || code !== '' || trace) { lastApi = api; lastCode = code; lastTrace = trace; }
  ui.diagnostics.hidden = !lastApi; ui.diagnosticText.textContent = `接口：${lastApi}\n错误码：${lastCode === '' ? '无（网络或资源问题）' : lastCode}\ntrace_id：${lastTrace || '无'}`;
}
function refreshButtons() {
  ui.upload.disabled = !selected || busy;
  ui.generate.disabled = !capture || busy;
  ui.file.disabled = busy;
  ui.pageNo.disabled = busy || !!capture;
}
function resetJob() {
  pollController?.abort(); pollController = null; jobId = null;
  ui.empty.hidden = false; ui.progressArea.hidden = true; ui.videoArea.hidden = true; $('videoEmpty').hidden = false;
  ui.video.pause(); ui.video.removeAttribute('src'); ui.video.load(); ui.resume.hidden = true; ui.stop.hidden = true;
}
function cancelableWait(ms, signal) {
  return new Promise((resolve, reject) => {
    if (signal.aborted) return reject(new DOMException('已取消', 'AbortError'));
    const timer = setTimeout(() => { signal.removeEventListener('abort', abort); resolve(); }, ms);
    function abort() { clearTimeout(timer); reject(new DOMException('已取消', 'AbortError')); }
    signal.addEventListener('abort', abort, { once: true });
  });
}
async function api(path, options = {}, signal, timeoutMs = 12000) {
  const endpoint = '/api/v1' + path;
  const timeout = new AbortController();
  const timer = setTimeout(() => timeout.abort(), timeoutMs);
  const abort = () => timeout.abort();
  if (signal?.aborted) timeout.abort(); else signal?.addEventListener('abort', abort, { once: true });
  try {
    let response;
    try { response = await fetch(endpoint, {...options, signal:timeout.signal}); }
    catch (e) { if (signal?.aborted) throw e; throw {message:timeout.signal.aborted ? '请求超时，请检查服务后重试。' : '无法连接后端，请检查服务和本地代理。', api:endpoint}; }
    if (!response.ok) throw {message:`服务连接异常（HTTP ${response.status}），请检查后端和代理。`,api:endpoint};
    let result; try { result = await response.json(); } catch { throw {message:'接口返回的数据无法解析。',api:endpoint}; }
    if (result.code !== 0) throw {message:result.msg || '接口调用失败',api:endpoint,code:result.code,trace:result.trace_id};
    if (!result.data) throw {message:'接口没有返回有效数据。',api:endpoint,trace:result.trace_id};
    lastApi = endpoint; lastTrace = result.trace_id || ''; lastCode = 0;
    return result.data;
  } finally { clearTimeout(timer); signal?.removeEventListener('abort', abort); }
}
function displayError(e) { if (e?.name === 'AbortError') return; showMessage(e?.message || '操作失败，请重试。',e?.api || '',e?.code ?? '',e?.trace || ''); }
async function validateFile(file) {
  if (!file || !['image/jpeg','image/png','image/webp'].includes(file.type) || !/\.(jpe?g|png|webp)$/i.test(file.name)) throw new Error('请选择 JPG、PNG 或 WebP 格式的图片。');
  if (file.size > 10 * 1024 * 1024) throw new Error('图片超过 10 MB，请压缩后重新选择。');
  const url = URL.createObjectURL(file);
  try { const img = new Image(); img.src = url; await img.decode(); if (Math.max(img.naturalWidth,img.naturalHeight) > 4096) throw new Error('图片长边不能超过 4096 像素，请缩小后重试。'); }
  catch(e) { throw new Error(e.message?.includes('4096') ? e.message : '图片无法读取，请重新选择。'); }
  finally { URL.revokeObjectURL(url); }
}
ui.file.addEventListener('change', async () => {
  const current = ++version; resetJob(); capture = null; selected = null; ui.previewWrap.hidden = true; showMessage(''); refreshButtons();
  const file = ui.file.files[0]; if (!file) return;
  try { await validateFile(file); if (current !== version) return; selected = file; }
  catch(e) { if (current === version) showMessage(e.message); }
  refreshButtons();
});
ui.upload.addEventListener('click', async () => {
  if (!selected || busy) return;
  const n = Number(ui.pageNo.value);
  if (!Number.isInteger(n) || n < 1 || n > 99) { showMessage('页码请输入 1 至 99 的整数。'); return; }
  resetJob(); capture = null; busy = true; refreshButtons(); showMessage('');
  uploadController = new AbortController();
  try {
    const body = new FormData(); body.append('image',selected); body.append('page_no',String(n));
    capture = await api('/capture',{method:'POST',body},uploadController.signal,15000);
    ui.preview.src = capture.preview_url; ui.previewWrap.hidden = false;
    ui.pageInfo.textContent = `第 ${capture.page_no} 页 · 原图 ${capture.image_width} × ${capture.image_height}`;
  } catch(e) { displayError(e); } finally { busy = false; uploadController = null; refreshButtons(); }
});
ui.preview.addEventListener('error', () => showMessage('图片已上传，但预览加载失败，请检查媒体代理。', '/previews'));
ui.video.addEventListener('error', () => { if (ui.video.getAttribute('src')) showMessage('视频加载或播放失败，请检查媒体代理和浏览器格式支持。','/videos'); });
function renderJob(job) {
  ui.status.textContent = jobStates[job.status] || `未知状态：${job.status}`;
  const progress = Number.isFinite(job.progress) ? Math.min(100,Math.max(0,job.progress)) : 0;
  ui.percent.textContent = `${progress}%`; ui.barFill.style.width = `${progress}%`; document.querySelector('.bar').setAttribute('aria-valuenow',String(progress));
  ui.stage.textContent = job.current_stage ? `当前阶段：${stageNames[job.current_stage] || job.current_stage}` : '';
  ui.stages.replaceChildren();
  for (const page of job.pages || []) for (const stage of page.stages || []) { const li = document.createElement('li'); li.textContent = `${stageNames[stage.name] || stage.name} · ${stageStates[stage.status] || stage.status}`; ui.stages.append(li); }
  if (terminals.has(job.status)) {
    ui.stop.hidden = true;
    const page = (job.pages || []).find(p => p.page_id === capture?.page_id) || job.pages?.[0];
    if ((job.status === 'done' || job.status === 'partial_failed') && page?.video_url) {
      const url = new URL(page.video_url, location.href); url.searchParams.set('job_id',job.job_id);
      ui.video.src = url.href; ui.video.load(); ui.videoArea.hidden = false; $('videoEmpty').hidden = true;
    }
    if (job.status === 'done' && !page?.video_url) showMessage('任务已完成，但没有返回视频地址。',`/api/v1/jobs/${jobId}`,'',lastTrace);
    if (job.status === 'failed' || job.status === 'partial_failed') { const error = job.error || page?.error; showMessage(`${jobStates[job.status]}${error?.msg ? '：' + error.msg : '，请查看联调信息并重试。'}`,`/api/v1/jobs/${jobId}`,error?.code ?? '',lastTrace); }
    if (job.status === 'cancelled') showMessage('任务已取消，请重新生成。',`/api/v1/jobs/${jobId}`,'',lastTrace);
    if (page?.degraded?.length) showMessage(`任务存在降级：${page.degraded.join('、')}`,`/api/v1/jobs/${jobId}`,'',lastTrace);
  }
}
async function poll(interval = 2000) {
  pollController?.abort(); const controller = new AbortController(); pollController = controller;
  ui.stop.hidden = false; ui.resume.hidden = true; const deadline = Date.now() + 300000;
  try {
    while (Date.now() < deadline) {
      await cancelableWait(Math.min(interval, Math.max(0,deadline-Date.now())),controller.signal);
      if (Date.now() >= deadline) break;
      const job = await api('/jobs/' + encodeURIComponent(jobId),{},controller.signal,Math.min(12000,Math.max(1,deadline-Date.now())));
      renderJob(job);
      if (terminals.has(job.status)) return;
      if (!['queued','running'].includes(job.status)) { showMessage(`不支持的任务状态：${job.status}，请反馈后端。`,`/api/v1/jobs/${jobId}`,'',lastTrace); return; }
    }
    showMessage('等待超时；后台任务可能仍在运行，可继续查询。',`/api/v1/jobs/${jobId}`,'',lastTrace); ui.resume.hidden = false;
  } catch(e) { if (e?.name !== 'AbortError') { displayError(e); ui.resume.hidden = false; } }
  finally { if (pollController === controller) { pollController = null; ui.stop.hidden = true; busy = false; refreshButtons(); } }
}
ui.generate.addEventListener('click', async () => {
  if (!capture || busy) return; resetJob(); busy = true; refreshButtons(); showMessage('');
  ui.empty.hidden = true; ui.progressArea.hidden = false; ui.status.textContent = '正在创建任务'; ui.percent.textContent = '0%'; ui.barFill.style.width = '0%'; document.querySelector('.bar').setAttribute('aria-valuenow', '0'); ui.stages.replaceChildren(); ui.stage.textContent = '';
  const controller = new AbortController(); pollController = controller;
  try {
    const result = await api('/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({page_ids:[capture.page_id],age_level:ui.age.value,force:false})},controller.signal);
    jobId = result.job_id; ui.status.textContent = jobStates[result.status] || result.status; pollController = null;
    await poll(Number.isFinite(result.poll_after_ms) && result.poll_after_ms > 0 ? result.poll_after_ms : 2000);
  } catch(e) { displayError(e); ui.status.textContent = '创建任务失败'; busy = false; refreshButtons(); }
});
ui.stop.addEventListener('click', () => { pollController?.abort(); ui.status.textContent = '已停止等待'; ui.resume.hidden = false; showMessage('已停止查询，后台任务可能仍在运行。'); });
ui.resume.addEventListener('click', () => { if (!jobId || busy) return; showMessage(''); busy = true; refreshButtons(); poll(2000); });
window.addEventListener('pagehide', () => { pollController?.abort(); uploadController?.abort(); });
refreshButtons();
