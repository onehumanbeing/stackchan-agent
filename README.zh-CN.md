# stackchan-agent（中文）

[English](README.md)（以英文版为准）

让 AI（Claude Code、Codex 或任何 OpenAI 兼容的模型）看见、说话并控制 StackChan：固件 + CLI + 本地 agent，手臂用 Feetech STS 总线舵机。

- **固件**（M5Stack CoreS3）：可替换风格的两眼表情、摄像头、麦克风和喇叭、STS3215 手臂（微雪 Bus Servo Adapter A，自动找 Grove 口）、机身自带的 SCS0009 头部舵机、Wi-Fi + mDNS `stackchan.local`。
- **协议**（`docs/protocol.md`）：NDJSON，USB 串口和 WebSocket :81 完全一样；二进制帧带 1 字节类型（摄像头 / 麦克风 / 喇叭）。
- **CLI**（`./stackchan`）：每条命令输出 JSON，方便 agent 读结果；用法见 `AGENTS.md`。
- **网页**（`./stackchan dash`）：摄像头、表情、3D 孪生、舵机状态、故障，以及 agent 的 Thinking 和 Steps，局域网内任何机器都能打开。
- **Agent**：每一轮把听到的话和摄像头画面交给模型，模型一行输出一个原语（说话、表情、手势、头、手臂），CLI 收到一行就执行一行。手势是 `cli/gestures.py` 里的关键帧，加新动作不用重新烧录。
- **语音**：说 "Hey Grok" 唤醒，它会应答、眼睛看上来（空闲时还会轻轻抬一下头），然后用自己的喇叭回话。`--lang zh|en` 选择说话语言，运行中可用 `./stackchan agent lang zh|en` 切换。语音识别用 whisper.cpp，语音合成用 Kokoro，都在本地运行。
- **数据采集**：每一轮都会记录到 `~/.stackchan/episodes`（画面、状态、听到的话、思考过程、执行的步骤），格式见 `docs/episodes.md`。

安装、烧录和运行命令见英文 README。
