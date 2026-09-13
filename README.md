# 飞牛音乐伴侣 (MusicFlow for fnOS)

<p align="center">
  <img src="fn-music-rebuild/ICON_256.PNG" width="128" height="128" alt="MusicFlow Icon" style="border-radius: 20px; box-shadow: 0 8px 24px rgba(0,0,0,0.2);">
</p>

<p align="center">
  <strong>专为 fnOS 飞牛私有云设计的音乐自动整理与元数据刮削工具</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/fnOS-Official%20App%20Ready-blue?style=flat-square&logo=linux" alt="fnOS Ready">
  <img src="https://img.shields.io/badge/Storage-Btrfs%20Reflink%20Support-success?style=flat-square" alt="Btrfs Reflink">
  <img src="https://img.shields.io/badge/Audio-Chromaprint%20Fingerprint-orange?style=flat-square" alt="Audio Fingerprint">
  <img src="https://img.shields.io/badge/License-MIT-green?style=flat-square" alt="License">
</p>

<p align="center">
  <img src="screenshot_dashboard.png" width="95%" alt="飞牛音乐伴侣控制台全貌" style="border-radius: 8px; box-shadow: 0 12px 36px rgba(0,0,0,0.35);">
</p>

---

## 📖 项目简介

很多 NAS 用户的下载目录中积累了海量音乐，常见问题包括：
- 包含大量网易云加密（`.ncm`）格式，部分播放器无法直接解码；
- 同一首歌存在多个不同格式或码率的版本（如同时存在 128kbps MP3 与无损 FLAC）；
- 歌曲内嵌标签缺失或繁简混杂，缺少内嵌专辑封面或同步歌词；
- 散乱存放，目录层级缺乏规律，导致播放器难以分类检索。

**飞牛音乐伴侣** 旨在提供一条自动化的整理流水线：通过声学波形特征与元数据分桶识别同曲目，完成解密、去重、标签补全、封面与歌词下载，并输出为飞牛原生音乐 App 便于扫描建库的标准目录结构（`歌手/专辑/曲目`）。

---

## ⚙️ 核心技术与工作原理

```mermaid
flowchart LR
    A[原始音乐文件夹
:ro 物理只读] --> B(Step 1: 格式探测与文件校验)
    B --> C(Step 2: NCM 临时沙盒解码)
    C --> D(Step 3: SHA-256 与文件排重)
    D --> E(Step 4: Chromaprint 声学指纹跨格式比对)
    E -->|规则优选高音质版本| F(Step 5: 标签 / 封面 / 滚动歌词补全)
    F -->|优先 Btrfs Reflink 克隆发布| G[整理后正式曲库
:rw 飞牛音乐扫描建库]
```

### 1. 源目录物理只读保护
- 输入目录在 Docker 容器层默认以只读（`:ro`）形式挂载；
- 流水线绝不调用针对源文件的写操作、删除操作或原地重命名，无论发生任何异常中断，原始文件均保持完整无损。

### 2. Btrfs 写时复制 (Reflink CoW)
- 飞牛私有云（fnOS）原生采用 Linux Btrfs 文件系统。在发布曲目时，流水线优先调用 `cp --reflink=auto -p`；
- **生效条件**：当原始目录与整理后目录位于**同一个 Btrfs 存储卷**时，底层共享物理数据块，大幅减少复制等待时间与磁盘空间占用；
- **回退机制**：若两目录跨卷（例如从 `/vol1` 整理至 `/vol2`）或目标盘为非 Btrfs 文件系统，系统将安全回退为常规物理文件复制。

### 3. NCM 隔离解码与沙盒管理
- 针对 `.ncm` 加密文件，流水线将其解码为临时 FLAC 置于专用运行沙盒中，用于提取音频指纹与元数据；
- 任务执行完毕后，临时解密生成的音频文件会即刻被全量销毁，不占用多余存储空间。

### 4. 跨格式声学波形指纹排重
- 集成开源 Chromaprint (`fpcalc`) 计算音频波形特征指纹；
- 在时长相近、特征吻合的同录音曲目组中，按文件质量规则（FLAC > WAV > MP3 高码率 > MP3 低码率）优先保留品质更优的版本，并记录归档其余冗余副本；
- *注：对于不同演奏者版本的古典乐、现场演唱会版（Live）或变奏混音版，指纹特征会有所差异，系统会尽量保留以避免误删。*

### 5. 多源元数据与歌词补全
- **华语源优化**：结合 QQ 音乐 Smartbox 联想与网易云音乐接口，内置常用简繁转换以提升华语歌曲与歌手匹配准确率；
- **限流防护**：严格遵循外部接口访问速率规范，内置超时与异常捕获，避免频繁请求被风控拦截；
- **歌词与封面**：自动补齐高清专辑封面与同步双语滚动歌词（支持内嵌 ID3/FLAC 标签与同名外挂 `.lrc` 文件）；
- **纯离线整理**：支持一键开启离线模式，完全跳过网络请求，仅凭本地已有标签与声纹完成整理。

### 6. 契合飞牛生态规范
- 遵循飞牛应用中心 FPK 规范打包，支持可视化安装向导；
- 整理后的输出结构符合飞牛原生音乐 App（`trim.music`）的建库规范，方便飞牛音乐即刻生成精美专辑封面墙与流动歌词。

---

## 🚀 部署与使用指南

### 方式一：飞牛应用商店一键安装（推荐）

1. 打开飞牛私有云（fnOS）桌面，进入 **应用中心**；
2. 搜索 **飞牛音乐伴侣**，点击安装；
3. 在安装向导中选择您授权的两个目录：
   - **原始文件夹（只读）**：存放未整理音乐的文件夹（如 `/vol1/1000/Downloads/Music`）；
   - **整理后文件夹（读写）**：存放整理后正式曲库的文件夹（建议在同一存储卷，便于享受 Reflink 秒级克隆）；
4. 安装完成后，在桌面打开应用即可进入 Web 控制台。

> **手动安装**：您也可以在 GitHub Releases 下载最新的 `.fpk` 文件，在飞牛应用中心选择“手动安装”上传安装。

---

### 方式二：Docker Compose 独立部署

如果您在其他 Linux 系统或自建 NAS 上运行，可参考以下 Compose 编排：

```yaml
version: "3.8"

services:
  music-companion:
    image: changchxy/fn-music-companion:1.0.0
    container_name: fn-music-companion
    restart: unless-stopped
    environment:
      - MUSIC_UI_PORT=8091
      - MUSIC_STATE=/appdata/v6-state
      - MUSIC_SAFE_SIMILARITY=0.997
      - MUSIC_SAFE_DURATION_DELTA=4.5
    volumes:
      # 原始音乐库：只读保护 (:ro)
      - /path/to/your/raw_music:/music/source:ro
      # 整理后曲库：读写 (:rw)
      - /path/to/your/library:/music/output:rw
      # 程序状态账本与数据库
      - ./music_flow_data:/appdata:rw
    ports:
      - "8091:8091"
    user: "1000:1000"
```

启动命令：
```bash
docker compose up -d
```
启动后在浏览器访问 `http://<NAS_IP>:8091` 即可进入管理面板。

---

## 🖥️ 控制台操作流程

1. **样本验证 (Sample Mode)**：
   - 首次使用建议先点击【开始样本验证 (10首)】；
   - 该阶段仅在沙盒中进行模拟处理，**不会向整理后目录写入任何音乐**，便于在控制台日志中查看解密与元数据匹配情况。
2. **全量整理 (Full Mode)**：
   - 验证通过后点击【开始全量整理】；
   - 流水线通过 SQLite 账本记录文件哈希与状态，支持断点续整，已处理过的文件不会重复拉取或重写。
3. **增量整理 (Incremental Mode)**：
   - 当源目录新增音乐时，点击【整理新增音乐】；
   - 仅对真新增、修改或此前失败的曲目进行针对性处理。
4. **纯离线模式**：
   - 若 NAS 处于局域网断网环境，可在设置中勾选【离线模式】，跳过所有云端 API 调用，纯本地极速运行。

---

## ☕ 赞助与支持

本项目为开源个人项目，永久免费。如果这款工具在日常整理音乐时为您提供了便利，欢迎扫描控制台“❤️ 赞助 / 关于”面板中的赞助码请作者喝一杯咖啡 ☕！

---

## 🤝 鸣谢与开源生态

特别致谢以下优秀的开源项目与基础构件：

- [dupsonic](https://github.com/zas/dupsonic) - 音频声纹聚类引擎
- [Chromaprint / fpcalc](https://github.com/acoustid/chromaprint) - 音频指纹提取算法库
- [taurusxin/ncmdump](https://github.com/taurusxin/ncmdump) - NCM 解密算法参考
- [Beets](https://github.com/beetbox/beets) & [MediaFile](https://github.com/beetbox/mediafile) - 音频标签处理框架
- [fnOS (飞牛私有云)](https://www.fnnas.com/) - 国产 NAS 操作系统与应用生态

---

## 📄 开源协议

本项目采用 [MIT License](LICENSE) 开源协议。
