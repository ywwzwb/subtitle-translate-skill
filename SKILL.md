---
name: translating-subtitles
description: Use when translating subtitle files (SRT字幕) or word-timestamped ASR JSON (timestamp.json, 词级时间戳) or 视频/音频文件 into bilingual Simplified Chinese + original-language ASS字幕, or when asked to 翻译字幕/校对字幕/生成双语字幕/添加注解字幕/srt转ass/听写json转字幕/视频转字幕/音频转字幕/用ASR转字幕. Triggers on keywords: subtitle, SRT, ASS, timestamp.json, mkv, mp4, mp3, 字幕翻译, 双语字幕, 注解字幕, srt to ass, translate subtitles.
---

# 字幕翻译 (Translating Subtitles)

## Overview

将字幕文件(SRT、带词级时间戳的 ASR JSON、或视频/音频)翻译为双语(简体中文 + 原语言) ASS 字幕。流程固定为 6 步, **必须按顺序全部执行, 不得跳过或改变顺序**:

1. 输入归一化 + ASR 转录(视频/音频; SRT 跳过; ASR 自动识别语种)
2. 时间戳 → YAML(脚本 + 模型复核)
3. 校对原文, 错误直接修正到 YAML(含分段重转修复)
4. 分批翻译(术语表 + 注解字幕)
5. 校对译文
6. 合并为 ASS(脚本)

脚本位于本 skill 的 `scripts/` 目录(与 SKILL.md 同级)。运行脚本时, `<skill_dir>` 指本 SKILL.md 所在目录。

## 环境与配置

- 需要 `ffmpeg`、`python`(含 `pyyaml`)、以及本地 ASR 工具 `transcribe.exe`(Qwen3-ASR GGUF)。
- transcribe.exe 路径解析: `run_transcribe.py --exe` > 环境变量 `TRANSCRIBE_EXE` > 默认 `C:\Users\zwb\Documents\Qwen3-ASR-Transcribe\transcribe.exe`。换机/换目录时设 `TRANSCRIBE_EXE` 即可, 不用改本文件。

## 工作目录(临时隔离)

每次翻译任务**独立一个临时工作目录**, 所有中间产物集中在一处, 完成后一键清理:

1. 建目录: `mkdir -p "$TEMP/opencode/<输入文件基名>"`(`$TEMP` 即系统临时目录, Windows 为 `%TEMP%`, 如 `C:\Users\zwb\AppData\Local\Temp`; 基名取输入文件名去扩展名)。
2. 把输入文件(视频/音频/SRT)复制进该目录, 之后所有操作都**在这个目录内**完成。
3. 所有中间产物(mp3、txt、srt、json、`main.yaml`、`seg*.yaml` 等)都生成在这里, **不污染输入文件所在目录**。
4. 完成后, 把最终 `.ass` 复制到输入文件所在目录(或用户指定位置)。
5. 用户要清理时, 直接删除整个工作目录即可。

> 术语表不受影响: `terminology.yaml` 在 skill 目录里全局共享(见第 4 步), 不放进工作目录。

## 第 1 步: 输入归一化 + ASR 转录

按输入类型准备音频:

- **视频**(mkv/mp4/mov 等): 先转单声道 16kHz MP3:
  `ffmpeg -y -i <input>.mkv -vn -map 0:a:0 -ac 1 -ar 16000 -c:a libmp3lame <input>.mp3`
- **音频**(mp3/wav/m4a 等): 同样转成统一单声道 16kHz mp3, 输出命名为 `<basename>.mono.mp3`(如 `demo.mp3` → `demo.mono.mp3`), 与视频路径的 `<input>.mp3` 区分, 避免与同名原文件冲突。
- **SRT**: 跳过本步(无需归一化与 ASR), 直接进入第 2 步(时间戳 → YAML)。

若输入是音频/视频, 运行 ASR 转录(**一律作用于上面归一化后的 mp3**: 视频为 `<input>.mp3`, 音频为 `<basename>.mono.mp3`):

`python3 <skill_dir>/scripts/run_transcribe.py <audio>.mp3 -y`

> 若 ASR 运行时缺失, 自动从 `ywwzwb/qwen3-asr-universal` 最新 release 下载匹配 `os/arch/后端` 的 zip 到 `~/.cache/opencode-translate/asr/` 并缓存。**后端自动探测**: 首次运行时探测本机最优方案(cuda→vulkan→metal→cpu, 依据 `nvidia-smi`/`vulkaninfo` 是否存在), 结果保存到本 skill 目录的 `config.yaml`(像 terminology.yaml 一样持久共享), 后续直接复用不再探测; 跨机器时做轻量复核, 失效则重新探测。**模型默认 1.7B**, 与后端一起存入 `config.yaml`, 首次由 q3asr 自动下载到 `~/.cache/q3asr/models/`(已有缓存则复用)。可用环境变量覆盖: `TRANSCRIBE_BACKEND`(cuda/vulkan/metal/cpu)、`TRANSCRIBE_MODEL`(如 1.7b/0.6b)、`TRANSCRIBE_ASR_VER`(默认 latest)。手动指定 `TRANSCRIBE_EXE` 仍为最高优先级。

- 产出同名 `<audio>.txt`、`<audio>.srt`、`<audio>.json`(词级时间戳 `[{text,start,end}]`, 秒)。
- **ASR 自动识别语种**(Qwen3-ASR 支持多语言); 如需强制指定语种再传 `-l <Language>`。
- 长音频: 先 `ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 <audio>.mp3` 得知时长, 给 bash 命令设置足够大的超时(本地 1.7B 模型约 0.05×时长 秒, 另加模型初始化)。

### 故障排查

- **ASR 失败**(退出码非 0): `run_transcribe.py` 失败时已自动打印 `logs/latest.log` 尾部, 按日志尾部定位; 若是本地 GPU/图形栈相关报错, 加 `--no-dml --no-vulkan` 重试。
- **乱码 `!!!` / 花屏**: 设置环境变量 `GGML_VK_DISABLE_F16=1` 后重新转录(Vulkan 禁用 fp16, 规避部分驱动不兼容)。
- **ffmpeg 不存在**: 立即停止, 先安装 ffmpeg 并确保在 PATH 中, 再继续第 1 步。

## 第 2 步: 时间戳 → YAML

按来源选择脚本:

- **音频/视频来源**(`<audio>.json`): 运行
  `python3 <skill_dir>/scripts/timestamp_to_yaml.py <audio>.json main.yaml`
  (可选 `--max-width` 每行宽度上限默认 30, `--gap` 分句停顿阈值秒默认 1.5)
- **SRT 来源**: 运行
  `python3 <skill_dir>/scripts/srt_to_yaml.py <input>.srt main.yaml`

生成中间文件 `main.yaml`:

```yaml
main:
  - from: 00:00:02,003
    to: 00:00:05,069
    en: |
      Narrator:
      TODAY ON "HOW IT'S MADE"...
  - from: 00:00:26,227
    to: 00:00:28,026
    en: |
      ALUMINUM FOIL...
```

**转换后必须复核(模型判断):** 脚本按句号/叹号/问号/长停顿自动分句, 并按宽度自动拆分过长句子, 已自动合并过短片段(句内孤片并入相邻、无句末标点的单字孤儿并入下句)。复核时:
- 检查分句是否自然; 过长或切分不自然的句子重新确定拆分点(优先在顿号、逗号等软分隔处)。
- **极短片段必须合并**: 若某条 cue 只有 1-2 个词或明显是从完整句中拆出的残片(如单独的 `mercury,`、`The`), 用 edit 并入上一句或下一句, 使每条字幕都是完整语块。标题性短句(`Cheese.`、`Tights.`)除外。
- 音频/视频来源: 重新拆分时**必须读取原始 JSON**, 按拆分后每个子片段的词 token 起止时间更新 `from`/`to`(SRT 无词级时间戳, 不适用此条)。

## 第 3 步: 校对原文

逐句阅读 `en` 字段, 找出拼写错误、听译错误、漏字, **直接用 edit 工具修正 `main.yaml` 中的 `en`**, 并在回复中列出修改点。禁止只在注解中提示而不改原文。

**保持 main.yaml 的标准格式**(`  - from:` + `    en: |` 块, 见第2步示例): 只做局部 edit, **禁止用脚本重排整个文件**(如 `yaml.safe_dump` 重写), 以免破坏缩进与块标量格式。

### 分段重转修复(幻觉/错误时间戳)

发现坏区域(单条字幕时长异常长、文本乱码、cue 时间重叠)时:

1. **选窗口**: 坏区域起点往前 ~3s、终点往后 ~3s, 得 `X` 与 `D = end - X`。
2. **重转该段**: `python3 <skill_dir>/scripts/run_transcribe.py <audio>.mp3 --seek-start X --duration D -y`(时间戳相对切片起点)。
3. **还原绝对时间**: `python3 <skill_dir>/scripts/timestamp_to_yaml.py <audio>.json seg.yaml --offset X`。
4. **核对覆盖**: 用 `--offset` 后 seg.yaml 最后一条的 `to` 应 ≈ `X + D`。若明显早于 `X + D`(重转输出被截断), 扩大窗口重转, 不要继续拼。
5. **拼回(必须传窗口参数)**: `python3 <skill_dir>/scripts/splice_yaml.py main.yaml seg.yaml main.new.yaml --seek-start X --duration D`。脚本会用**请求窗口**而非段内容范围做删除, 并校验覆盖——若重转段被截断, 脚本会报错拒绝拼回(必要时可 `--force`, 但先扩大窗口重转为宜)。
6. **复核**: 检查 splice 输出(删除清单 + 字数警告 + LOSS 行)。**每次 splice 都会默认打印被删 cue 清单**; 若出现 `LOSS:` 行, 说明有条被删 cue 的文本没在重转内容里出现——若是完好句子, 扩大窗口重转。确认无漏词后, 用 edit 以 `main.new.yaml` 内容替换 `main.yaml`; 若丢词, 扩大窗口重转或手工 edit 修正。

**必须用 `splice_yaml.py` 拼回, 禁止手工拼接重转片段**: 手动把新 cue 贴进 main.yaml 极易产生重复/重叠 cue(同一 from 出现两次), 用脚本按时间窗口替换可避免。替换后若发现重复 `from`, 说明拼接过当, 用 splice 重做。

## 第 4 步: 分批翻译

**开始翻译前, 先读取 `<skill_dir>/terminology.yaml`(不存在则创建空文件)。** 术语表存放在本 skill 的目录里(全局安装时即机器级), **跨视频、跨项目、跨会话持久共享**, 保证不同视频里同一人名/地名/专有名词译法一致。翻译中遇到新术语, 先把它加进 `<skill_dir>/terminology.yaml` 再使用; 匹配不区分大小写。

> 说明: 若 `<skill_dir>` 与当前项目不同(全局安装), 术语表就是全局唯一的一份; 项目里不再单独维护 `terminology.yaml`。

用 edit 工具向每个字幕条目写入 `chs` 字段。**每批最多翻译 20 句, 严禁一次性输出全部字幕的翻译**——每次 edit 只写入当前批次, 上一批确认后再处理下一批。

```yaml
main:
  - from: 00:00:02,003
    to: 00:00:05,069
    en: |
      Narrator:
      TODAY ON "HOW IT'S MADE"...
    chs: |
      旁白：
      今天的《造物小百科》……
```

### 翻译规则

1. **意译优先, 不逐字逐句。** 按汉语语序和句式长度调整词序、位置, 可合并或拆分句子, 确保中文通顺自然。
2. **专有名词统一走术语表。** 人名、地名、作品名、品牌名等, 在 `terminology.yaml` 中统一翻译, 并每次翻译前先读取。术语匹配不区分大小写。遇到新术语时先加入术语表再使用:

```yaml
terminology:
  Susan: 苏珊
  Texas: 德州
  HOW IT'S MADE: 造物小百科
```

3. **句尾标点。** 译文正文句末若最后一个字符是句号 `。` 或逗号(全角 `，` 或半角 `,`), 直接去掉。例: "欢迎收看本期节目。" → "欢迎收看本期节目"。句号/逗号只允许出现在句中, 不得作为译文句尾。
4. **注解字幕。** 字幕中出现中文语境少见的当地习俗、节日、专业名词、英制单位等, 添加 ≤20 字(约 4 字/秒)的简短注解, 写入 `main.yaml` 的 `annotations` 列表。**同一术语只在第一次出现时注解。**

```yaml
annotations:
  - from: 00:00:02,003
    text: 造物小百科：科普纪录片栏目
```

注解规则:
- 每个注解 ≤20 字, 尽量简洁。
- `from` 与对应字幕的开始时间对齐。
- `to` 不必填写, `yaml_to_ass.py` 按 4 字/秒 自动计算结束时间。
- 同一句(开始时间相同)若出现多个注解, 脚本会合并为一条事件, 上下并列展示。
- 连续注解若前一条结束时间晚于后一条开始时间, 脚本会将前一条结束时间钳制到后一条开始之前, 避免时间重叠。
- **英制单位**: 注解直接给出该句具体数值的标准国际单位换算, 如 "500磅≈227公斤"、"60英里≈96.6公里/时"、"62°F≈17°C", **不解释单位本身的含义**(如"英制重量单位")。单位换算用 ≈ 表示近似; 数值不同时每次出现都需换算, 不受"首次出现"限制。

## 第 5 步: 校对译文

通读全部 `chs`, 检查错译、漏译、术语不一致、时间轴错位, 用 edit 工具修正。

## 第 6 步: 合并 ASS

运行: `python3 <skill_dir>/scripts/yaml_to_ass.py main.yaml output.ass`

合并完成后, **把成品 `.ass` 复制到输入文件所在目录**(如视频旁边), 便于用户直接使用; 工作目录里的中间产物留给用户按需清理。

生成格式(模板内嵌于脚本, 要点如下):

```
[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Translation,Noto Sans CJK SC,56,&H00FFFFFF,&H000000FF,&H00141414,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,80,80,81,1
Style: Original,Noto Sans CJK SC,36,&H00FFFFFF,&H000000FF,&H00141414,&H80000000,-1,0,0,0,100,100,0,0,1,2,1,2,80,80,45,1
Style: Annotation,Noto Sans CJK SC,26,&H00FFE066,&H000000FF,&H00141414,&H80000000,-1,0,0,0,100,100,0,0,1,1,1,7,40,40,20,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
```

**输出为三条独立轨道**, 便于后期逐轨调整样式(各轨道用独立的 Layer 与 Style, 可在 Aegisub/剪辑软件中分开编辑):

| Layer | Style | 内容 | 字号/位置 |
|-------|-------|------|-----------|
| 0 | Translation | 简体中文译文 | fs56, 底栏主行 |
| 1 | Original | 原语言文本 | fs36, 紧贴译文下方 |
| 2 | Annotation | 注解 | fs26, 左上角 |

布局要求:
- **译文为主**: 底栏大字号(Layer 0)。
- **原文为辅**: 译文下方小字号(Layer 1)。
- **注解在左上角**(Layer 2, Alignment 7)。

示例事件:

```
Dialogue: 0,0:00:02.00,0:00:05.06,Translation,,0,0,0,,今天的《造物小百科》……
Dialogue: 1,0:00:02.00,0:00:05.06,Original,,0,0,0,,Narrator: TODAY ON "HOW IT'S MADE"...
Dialogue: 2,0:00:02.00,0:00:03.62,Annotation,,0,0,0,,造物小百科：科普纪录片栏目
```

## 常见错误 (Common Mistakes)

| 错误 | 正确做法 |
|------|----------|
| 跳过 YAML 直接输出 ASS | 必须先转 `main.yaml`, 翻译再合并 |
| 手写 ASS 代替脚本 | 用 `yaml_to_ass.py` 合并, 注解时间由脚本计算 |
| 一次性翻译全部字幕 | 每批 ≤20 句, 分批 edit |
| 人名地名前后译法不一致 | 写入 `terminology.yaml`, 每次先读取 |
| 注解超过 20 字 | 压缩, 只保留必要信息 |
| 注解结束时间随手填 | 交给脚本按 4 字/秒 计算 |
| 同一句多个注解未并列 | 脚本自动合并为上下两行 |
| 英制单位注解只解释单位含义 | 直接给出该数值的 SI 换算(如 "500磅≈227公斤") |
| 原文错误只加注解不改 | 直接修正 `main.yaml` 的 `en` |
| 同一术语反复注解 | 只在第一次出现时注解 |
| 译文句尾保留句号/逗号 | 去掉句末的 `。`、`，`、`,` |
| 跳过第 5 步校对 | 出 ASS 前必须通读 `chs` |
| 重转片段时间轴不对 | 用 `--offset X` 还原绝对时间 |
| 直接删旧字幕不重转 | 走分段重转: 重转 → --offset → splice 拼回 |
| 幻觉时间戳靠脚本钳制 | 用分段重转修复, 不用钳制 |

## Red Flags

- 生成 `.ass` 之前没有 `main.yaml`
- 手写 ASS 事件而不是用 `yaml_to_ass.py`(注解结束时间必须由脚本计算)
- 单个回复中翻译超过 20 句
- 翻译前没有读取 `terminology.yaml`
- 注解文本超过 20 字
- 同一人名/地名出现多个译法
- 译文句尾出现句号 `。` 或逗号
- 跳过第 5 步直接出 ASS
- 输入是视频/音频却跳过了 ASR 转录直接手写字幕
- splice 输出未核对字数警告就替换 main.yaml
- 分段重转后没有加回 `--offset` 就拼接
- 中间产物直接生成在输入文件所在目录(应在临时工作目录内完成, 成品再拷出)

以上任意一条出现, 立即停下纠正流程。
