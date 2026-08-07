# 字幕翻译技能 (translating-subtitles)

一个 [opencode](https://opencode.ai) 技能: 把**视频 / 音频 / SRT 字幕**自动翻译成**双语(简体中文 + 原语言) ASS 字幕**。

- 本地 ASR 转录(Qwen3-ASR GGUF, 支持多语言自动识别)
- 词级时间戳 → 自动分句 / 拆行 / 短片段合并
- 注解字幕(含英制单位自动换算 SI)
- 三轨 ASS 输出(译文 / 原文 / 注解各自独立, 便于后期调样式)
- 全局术语表, 跨视频保持译名一致

## 工作流(6 步)

1. **输入归一化 + ASR 转录**: 视频用 ffmpeg 转单声道 16kHz MP3, 再用 `transcribe.exe` 生成词级时间戳 `[{text,start,end}]`。
2. **时间戳 → YAML**: 自动分句(句号/叹号/问号/长停顿)、按宽度拆行、合并过短片段; 模型复核拆行并读取 JSON 校准时间。
3. **校对原文**: 修正听写错误(幻觉/时间戳塌缩区域走"分段重转"修复)。
4. **分批翻译**(每批 ≤20 句): 术语表统一 + 注解字幕。
5. **校对译文**。
6. **合并 ASS**: 三轨输出, 成品拷贝到输入文件所在目录。

每次任务在临时目录下独立工作, 完成后只把成品 `.ass` 拷贝出来, 便于一键清理。

## 安装

技能文件即本仓库内容(`SKILL.md` + `scripts/` + `tests/` + `terminology.yaml`)。

**全局安装**(所有项目可用):

```bash
mkdir -p ~/.config/opencode/skills
cp -r . ~/.config/opencode/skills/translating-subtitles
```

**项目级安装**(仅当前项目):

```bash
mkdir -p .opencode/skills
cp -r . .opencode/skills/translating-subtitles
```

安装后**重启 opencode** 生效。之后把视频/音频/SRT 丢进会话, 说"翻译这个视频/字幕"即可。

## 依赖

- **Python 3** + `pyyaml`(`python -m pip install pyyaml`)
- **ffmpeg**(视频转音频、libass 校验)
- **Qwen3-ASR 工具**: [Qwen3-ASR-Transcribe](https://github.com/HaujetZhao/Qwen3-ASR-GGUF), 提供 `transcribe.exe`(默认路径 `C:\Users\zwb\Documents\Qwen3-ASR-Transcribe\transcribe.exe`, 可用环境变量 `TRANSCRIBE_EXE` 或 `--exe` 覆盖)

## 脚本

| 脚本 | 作用 |
|------|------|
| `scripts/run_transcribe.py` | 调用 transcribe.exe, 解析路径 + 分段重转参数 |
| `scripts/timestamp_to_yaml.py` | 词级时间戳 JSON → `main.yaml`(分句/拆行/合并短片段/`--offset`) |
| `scripts/srt_to_yaml.py` | SRT → `main.yaml` |
| `scripts/splice_yaml.py` | 把分段重转片段非破坏式拼回 `main.yaml`(防重复 cue) |
| `scripts/yaml_to_ass.py` | `main.yaml` → 三轨 ASS(译文/原文/注解) |

## 测试

```bash
cd translating-subtitles
python -m unittest discover -s tests -p 'test_*.py'
```

## 许可证

MIT
