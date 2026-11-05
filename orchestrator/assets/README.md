# 本地 MOCK 媒体素材

- mock.mp4：320×240、25 fps、约 1 秒 H.264 视频，画面写有 MOCK DEMO ONLY；不代表上传页面的识别或生成结果。
- mock.mp3：约 1 秒、24 kHz 单声道静音 MP3；没有真实配音。

两份素材均在本机生成，不下载第三方内容。生成阶段将真实文件复制到 DATA_DIR 的固定契约路径后才返回可访问 URL，运行时不需要 FFmpeg。

制作方式：Pillow 绘制纯色文字画面；使用 imageio-ffmpeg 0.8.1 携带的 FFmpeg，以 libx264/yuv420p/faststart 编码视频，以 anullsrc/libmp3lame 编码音频。两份素材均已通过 FFmpeg 完整解码验证。imageio-ffmpeg 仅为素材制作工具，不是服务运行依赖。

静音音频与测试视频的编码时长可能包含编码器填充，Mock JSON 使用名义 1 秒；真实模块接入时必须替换为实际配音、视频和实测时长。
