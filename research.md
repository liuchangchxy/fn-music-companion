# NAS 音乐整理流水线可行性调查

调查目标：验证既定计划能否在飞牛 OS NAS 上落地。调查过程中不修改真实音乐文件。

调查日期：2026-09-10

## 1. NAS 当前实际情况

SSH 免密连接已验证成功：`FnNas (192.168.1.11)`，用户 `chang`，Docker Server `28.5.2`，CPU 架构 `x86_64`。

目录与计划的对应关系：

```text
计划 incoming  -> /vol2/1000/Download/音乐/整理前
计划 library   -> /vol2/1000/Download/音乐/整理后
```

飞牛自带音乐进程为 `trim.music`。读取其只读 SQLite 数据库确认，当前共享音乐库路径为：

```text
/vol2/1000/Download/音乐/整理后
```

这与“飞牛音乐只扫描处理完成后的正式曲库”的计划一致。

当前整理前目录统计：

```text
总文件约 3213 个，约 80 GB
.ncm  1143
.flac 1289
.mp3  727
.ape  2
.wav  2
.aac  1
```

整理后目录已经有历史曲库。飞牛数据库记录 4395 条音频记录，其中 2360 个对应文件仍存在；文件类型主要是 FLAC 和 MP3。飞牛数据库有 SHA256，但当前 `fingerprint` 字段为 0 条非空记录，说明不能依赖飞牛自带数据库完成 Chromaprint 音频去重。

## 2. 组件调查

### Music Tag Web

官方仓库：https://github.com/xhongc/music-tag-web

结论：可用 Docker 运行，支持 FLAC、APE、WAV、MP3、M4A 等格式，具备批量标签编辑、刮削、歌词、封面和文件整理能力；官方文档给出了将 NAS 音乐目录以读写方式挂载到 `/app/media` 的方案。

限制：目前公开资料确认的是 Web UI 和 Docker 部署，没有确认稳定公开的 REST API 或 CLI。按照原计划，第一阶段不应通过模拟浏览器点击强行自动化；可以先把它作为松耦合的人工批量刮削工具。

补充源码核查：当前仓库确实存在 Django REST Framework 路由，挂载在 `/api/`，包括 `file_list`、`music_id3`、`update_id3`、`batch_update_id3`、`fetch_id3_by_title`、`fetch_lyric` 等接口，前端也直接调用这些接口。仓库同时使用 JWT 登录。这个接口目前足以证明“可以通过 API 集成”，但它是项目内部 API，尚未证明有稳定版本承诺；应锁定镜像版本并在升级前回归测试。

结论：自动集成技术上可行，但不应依赖 `latest` 或模拟浏览器；第一版可先人工操作，第二阶段再针对锁定版本封装 API 适配器。

### NCM 解密

候选项目：https://github.com/chaunsin/netease-cloud-music

官方提供 `ncmctl` Docker 镜像，并提供批量解密命令：

```bash
ncmctl ncm /path/to/ncm/files -o /path/to/output
```

结论：具备计划所需的批量 CLI 能力，可以作为外部解密器调用。需要注意网易云登录/API 风控，但“解密已有 `.ncm` 文件”与“自动下载网易云”是两个不同问题；本计划只必须解决前者。

尚未完成：在 NAS 上拉取镜像并对真实文件进行解密测试。该操作会产生输出文件，必须先使用复制出来的测试样本。

实测结果（使用临时目录中的单个样本，不触碰原文件）：`chaunsin/ncmctl:latest` 镜像可以拉取并启动，但对 `5 Seconds of Summer - Teeth.ncm` 解密失败：`ncm: artist id has type string`，没有生成输出文件。因此该工具不能未经测试就作为唯一解密器。

备用候选：`taurusxin/ncmdump`。其官方发行说明明确提到修复网易云 3.0 后部分 NCM 文件无法识别的问题，并提供 Linux 构建方式；但新版 Linux 构建依赖 TagLib 2.x，部署复杂度高于 ncmctl，需要在下一个测试样本中验证。

进一步实测：官方 `ncmdump-1.5.1-linux-amd64.zip` 在 NAS 上无法启动，要求 `GLIBC_2.38`，而飞牛 NAS 当前为 Debian glibc 2.36。旧版 1.2 提供 Linux amd64 包，但本次从 NAS 下载 GitHub release 时网络连接失败，尚未完成解密验证。

因此 NCM 环节的现实落地方式不是直接下载一个现成二进制，而是：在兼容 NAS glibc 的 Docker 基础镜像中构建 `ncmdump`，或继续寻找静态链接/Go 版本；构建后必须用真实 `.ncm` 样本验证。

随后从本地下载并传入 NAS 的 `ncmdump` 1.2 Linux amd64 二进制成功处理了同一个真实样本：生成 `5 Seconds of Summer - Teeth.flac`，输出大小 24,400,718 bytes，原 `.ncm` 未被删除。该版本不支持 `-o` 输出目录参数，只能在源目录生成结果，因此控制器需要使用临时独立目录并自行完成校验、改名和移动。

### FFmpeg / ffprobe

NAS 已安装：

```text
ffmpeg / ffprobe 8.1.1-mediasrv
```

结论：格式识别、时长、码率、采样率、位深、声道和解密结果校验可以直接复用 NAS 现有工具，不必自己实现。

### Chromaprint / fpcalc

官方项目：https://github.com/acoustid/chromaprint

官方提供 Linux x86_64 的 `fpcalc` 发布包；Chromaprint 明确支持用于近似相同音频识别和重复音频检测，`fpcalc` 可输出 JSON，适合被控制器调用。

结论：技术上完全符合计划。NAS 当前未安装 `fpcalc`，应把官方二进制或构建结果放入专用工具容器，而不是修改系统环境。

重要边界：Chromaprint 生成的是音频指纹，不会自动理解 Live、Remaster、Radio Edit 等业务版本。相似度阈值和版本判定必须用真实样本验证，疑似结果不能自动删除。

实测：官方 `fpcalc 1.6.1` Linux x86_64 包在 NAS 上可运行，并成功对前述解密出的 FLAC 输出 JSON 指纹（时长 204.89 秒）。因此指纹生成环节已在目标 NAS 上打通；尚未完成的是对成对 MP3/FLAC 样本做相似度阈值标定。

### dupsonic

官方仓库：https://github.com/zas/dupsonic

项目使用 Chromaprint，支持 MP3、FLAC、M4A/AAC、APE 等格式，提供增量扫描、重复组、质量排序和 Linux Web UI。其定位与本计划的“跨格式重复检测”高度匹配。

结论：优先作为查重组件或实现参考，不直接假设它能完成完整的 incoming 状态机、NCM 解密、数据库事务和 Music Tag Web 编排。其 GPL-2.0-or-later 许可证也需要在最终分发方式确定后单独处理。

实测：官方 `dupsonic 0.2.5` Linux x86_64 发布包要求 `GLIBC_2.39`，飞牛 NAS 的 glibc 2.36 无法直接运行。因此不能直接使用官方预编译包，需要自行在兼容基础镜像中构建，或只复用其匹配算法思路。

使用 `fpcalc 1.6.1` 对现有曲库中 `Beyond - Amani.mp3` 与 `Beyond - Amani.flac` 测试：两者时长分别为 288.32 秒和 289.36 秒，均能生成指纹，但压缩后的指纹字符串不相同。这是预期现象，也说明控制器不能简单比较字符串相等，必须实现或复用 Chromaprint 指纹相似度计算，并结合时长阈值。

## 3. 对原计划的可行性判断

| 计划要求 | 判断 | 依据 |
|---|---|---|
| 不依赖 Windows | 可行 | NAS 为 Linux，Docker 可用 |
| Docker 部署 | 可行 | Docker 28.5.2，x86_64 |
| NCM 转普通音频 | 可行但需测试 | `ncmctl` 有批量解密 CLI/镜像 |
| MP3/FLAC/M4A/APE 混合格式 | 可行 | ffprobe 与 Chromaprint/dupsonic 均覆盖主要格式 |
| 全历史曲库增量去重 | 可行 | fpcalc/Chromaprint 可生成持久化指纹；需要自建 SQLite 索引 |
| 中文元数据、歌词、封面 | 可行 | Music Tag Web 已具备相应 Web 功能 |
| 自动调用 Music Tag Web | 未证实 | 尚未发现稳定公开 API/CLI |
| 只保留一份正式音频 | 可行但需严格事务设计 | incoming/library 同一存储池，可使用 rename/mv；删除必须后置 |
| Live/Remaster 不误删 | 可行但不能只靠指纹阈值 | 必须结合标题版本词、时长和人工确认队列 |
| 长期自动运行 | 可行 | 自建控制器使用 watchdog/inotify + SQLite 状态机 |

## 4. 当前结论

原计划总体可行，且 NAS 目录实际情况与计划结构吻合。最小可行技术路线是：

```text
专用 Docker 工具容器
  ├── Python 控制器 + SQLite
  ├── ffprobe（NAS 已有，也可容器内固定版本）
  ├── fpcalc
  └── NCM 解密 CLI

Music Tag Web（独立容器，第一阶段人工操作）
飞牛自带音乐（只扫描 整理后）
```

当前不能承诺的部分只有：

1. NCM 解密器在真实样本上的兼容性和输出质量；
2. Chromaprint 对本曲库中不同版本的误匹配率；
3. Music Tag Web 是否存在可长期依赖的自动接口。

因此下一步应严格进入 Phase 2 前的测试准备：复制少量测试文件，安装/运行工具容器，验证 `ffprobe + NCM 解密 + fpcalc`，再决定是否需要自己实现去重控制器。未经测试，不对真实曲库执行自动删除或批量移动。

## 5. 最终可行性结论

原计划不是“安装几个容器即可完成”的方案，而是“成熟工具 + 一个可靠控制器”。按当前证据，建议保留原计划，但调整组件落地方式：

```text
飞牛自带音乐       只扫描 /整理后
Music Tag Web       独立容器，锁定版本，通过内部 API 或人工操作
ncmdump 1.2         作为已验证的 NCM 解密后端
ffprobe             使用 NAS 已有版本或固定容器版本
fpcalc 1.6.1        作为指纹生成后端
SQLite 控制器       自己开发，负责相似度、状态、事务和文件生命周期
```

不能直接采用的候选：`ncmctl`（真实样本失败）、`ncmdump 1.5.1`（glibc 不兼容）、`dupsonic 0.2.5`（glibc 不兼容）。这并不否定原方案，只否定“直接使用其官方现成二进制”的假设。

最终风险等级：

```text
目录与飞牛扫描       已验证，可行
Docker 与 NAS 架构    已验证，可行
NCM 解密              已验证一例，可行但需扩大样本
格式信息读取          已验证，可行
指纹生成              已验证，可行
指纹相似度判定        尚需实现并用样本标定
中文刮削/歌词/封面    工具能力和内部 API 已确认，需锁版本回归
长期自动运行          架构可行，需 Phase 2/4 实现
安全删除与替换        设计可行，必须经过测试后启用
```

结论：计划具备落地条件，但当前证据只支持“可以进入小样本 Phase 2”，不支持立即对 80GB 真实曲库自动删除。真正的上线门槛是：完成至少一组 MP3/FLAC、Live、Remaster、损坏文件和 NCM 的自动化测试，并让所有破坏性操作默认关闭。
