# 百炼接口与本地依赖核实目录

核实日期：2026-11-17—18。目录是离线接入依据，不代表当前账户已经拥有模型权限。默认北京；其他地域可保存配置，但未核实全链路价格与CosyVoice非实时HTTP能力前拒绝计费。所有价格以账户控制台确认及最终官方账单为准，不假设免费额度或促销。

|用途|本版本Model ID / 本地版本|调用方式与主要约束|
|---|---|---|
|OCR|PaddleOCR3.3.2 / PaddlePaddle3.2.0 / PP-OCRv5_mobile_det、PP-OCRv5_mobile_rec|独立Python3.12环境；CPU；仅下载轻量OCR权重；8个关键模型文件SHA见config/paddle-model-sha256.json|
|VLM|qwen3-vl-plus|OpenAI兼容chat/completions；JPEG Data URI；JSON；enable_thinking=false；复用M2安全解析器，缺失safety即拒绝|
|故事 / Agent|qwen-plus|同上；整本故事结构化JSON，完整页身份/顺序/分镜数量/字数/安全校验；问答基于书与当前页的服务端上下文，搜索关闭|
|语音问题转写|qwen3-asr-flash|兼容chat/completions + input_audio.data=Base64 WAV；asr_options language=zh、enable_itn=false；先真实解码、检查≤60秒及非静音|
|TTS|cosyvoice-v3-flash|POST /api/v1/services/audio/tts/SpeechSynthesizer；input.text/voice/format=mp3/sample_rate=24000/rate=0.9；output.audio.url临时下载；实际已安装DashScope2.1.0并做SDK构造体等价测试|
|默认音色|storybook_female_warm → longyan_v3|官方“龙颜”：温暖春风女，30—35岁，普通话/英语；仅合法系统音色，不调用克隆；听感、情绪、儿童适配待真实试听，不据目录代签|
|备选音色|longanhuan|官方“龙安欢”：20—30岁元气成年女声。配置仅允许本轮核实音色；不接受任意克隆Voice ID|
|图生视频|wan2.6-i2v-flash|POST /api/v1/services/aigc/video-generation/video-synthesis；X-DashScope-Async=enable；input.img_url=JPEG Data URI；2—15整数秒、720P/1080P；audio=false、prompt_extend=false、watermark=true|
|异步查询/取消|同一百炼地域与Key|GET /api/v1/tasks/{id}；默认15秒轮询，仅GET有界重试；POST /api/v1/tasks/{id}/cancel只能取消PENDING；Task ID及成功URL通常24小时有效|
|后期|FFmpeg / FFprobe，当前本机FFmpeg9.0.2|Wan动态片段加CosyVoice音频及SRT；重建连续音视频时间戳解决分页AAC DTS冲突；中文字体验证SHA；最终完整解码与时间轴校验|

默认共享域名 `https://dashscope.aliyuncs.com`，兼容路径 `/compatible-mode/v1`。可输入业务空间ID，使用官方推荐 `https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com`；禁止任意URL以避免SSRF及Key外送。新加坡域名 `https://dashscope-intl.aliyuncs.com` / `{WorkspaceId}.ap-southeast-1.maas.aliyuncs.com` 只作配置展示，完整链路暂不计费。

|北京公开单价|本轮核实值|预算使用|
|---|---|---|
|Qwen3-VL-Plus|输入≤32K：1元/百万输入、10元/百万输出；32K—128K：1.5/15；128K—256K：3/30|图片限制至2048边，OCR文本限制12000字；按页估算并加全任务余量|
|Qwen-Plus 非思考|≤128K：0.8/2元每百万；128K—256K：2.4/20；256K—1M：4.8/48|故事物料≤128000 UTF8字节，按较高单价预留并加余量；输出max_tokens配置受限|
|CosyVoice v3 Flash|1元/万字符|有界配音字数，不以免费额度抵扣|
|Wan2.6 I2V Flash，audio=false|720P 0.15元/秒；1080P 0.25元/秒|每页分镜上限×15秒保守预留；实测音频后选择ceil(duration)，超过15秒直接失败，不补交未批准收费任务|
|Qwen3 ASR Flash|0.00022元/秒|每问题最多60秒；问答最低确认1元上限，和主生成共享150元账户|

官方来源（原始事实为节选整理，未复制整页）：

- [百炼模型价格](https://help.aliyun.com/zh/model-studio/model-pricing)
- [Qwen3-VL-Plus能力](https://help.aliyun.com/zh/model-studio/qwen3-vl-plus)
- [OpenAI兼容Chat接口](https://help.aliyun.com/en/model-studio/qwen-api-via-openai-chat-completions)
- [结构化JSON](https://help.aliyun.com/en/model-studio/qwen-structured-output)
- [CosyVoice非实时Python SDK](https://help.aliyun.com/zh/model-studio/cosyvoice-tts-python-sdk)
- [官方音色目录](https://help.aliyun.com/zh/model-studio/cosyvoice-voice-list)
- [Wan首帧图生视频](https://help.aliyun.com/zh/model-studio/legacy-image-to-video-api-reference/)
- [异步任务管理](https://help.aliyun.com/zh/model-studio/manage-asynchronous-tasks)
- [Qwen-ASR接口](https://help.aliyun.com/zh/model-studio/qwen-asr-api-reference)
- [PaddleOCR官方源码与版本](https://github.com/PaddlePaddle/PaddleOCR/tree/v3.3.2)
- [FFmpeg官方链接的Windows构建](https://github.com/FFmpeg-Builds/FFmpeg-Builds/releases)

Paddle与CI的PyYAML锁不同，因此两个环境隔离；不降低原有依赖或测试断言。网页是原生JS/CSS，无npm运行依赖。浏览器自动测试可使用已安装Edge/Chrome，否则安装Playwright Chromium；不下载本地Qwen、Wan或CosyVoice模型。
