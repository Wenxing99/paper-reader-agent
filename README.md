# paper-reader-agent

`paper-reader-agent` 是一个独立的本地论文阅读 Web App。它围绕个人科研工作流来设计：

- 左栏只放整篇论文的阅读导图
- 中间只放原始论文阅读面
- 右栏只放基于全文上下文的 AI chat
- 选中文本后只弹出 `解释 / 翻译`，不会自动执行
- 缓存、导图、后续导出都优先落在本地文件

仓库根目录下的 [AGENTS.md](./AGENTS.md) 是当前项目的最高优先级约束。

Current priorities and staged implementation notes live in [ROADMAP.md](./ROADMAP.md).

## Current Scope

- Flask 后端 + 原生 JavaScript/CSS 前端
- repo-local `.venv` 独立环境
- 导入单篇 PDF，或扫描本地论文目录
- 生成整篇论文阅读导图
- 顶部工具区压缩为紧凑操作条，尽量把可视空间留给 PDF
- 中间列默认连续阅读整篇论文，也可切换回单页模式
- 中间列支持缩放、适应宽度和跳页
- 中间列现已使用 repo 内 vendored 的 `PDF.js` 作为本地渲染层，不要求 Node 构建链
- 左栏导图、中间 PDF、右栏 chat 在桌面布局下各自独立滚动
- 左栏和右栏在桌面布局下支持拖拽调宽，中间 PDF 会随之自适应变宽或变窄
- 中间列支持选中文本后弹出 `解释 / 翻译`
- 右侧 chat 默认注入全文导图和相关页面摘录，而不是只盯当前页
- 为未来 Obsidian 导出预留本地数据结构和目录
- 内建本地 Codex bridge 启动链，避免依赖额外仓库或中间层
- Left reading guide and right chat now render Markdown and math.

## Reading Flow

- 导入 PDF 时会优先完成文件保存和基础元数据读取，不再默认阻塞到整篇文本缓存完成
- 打开论文后，阅读器会先准备首批页面，剩余页面文本层随着滚动按需加载
- 全文文本缓存会在后台继续补齐，这样可以兼顾“先开始读”和“后续导图 / chat 需要全文上下文”
- 如果刚导入完就立刻发起整篇阅读导图或全文 chat，第一次仍可能等待全文缓存补完

## Open-Source Hygiene

这个仓库计划按“代码公开、论文内容不公开”的方式维护。

- 导入的 PDF、渲染页图、抽取文本、阅读导图缓存都只保留在本地忽略目录里
- `data/papers/` 和 `data/exports/` 默认不进入 git，仓库中只保留 `.gitkeep`
- 不要把真实论文页面截图、样例 PDF 或大段提取文本直接提交到仓库
- 准备公开发布前，先运行：

```powershell
.\.venv\Scripts\python.exe scripts/check_repo_hygiene.py
```

这个检查会帮助你发现误入 git 的论文内容、缓存文件和临时编辑文件。

当前 PDF 处理栈已经按宽松许可路线整理：

- `pypdf`：BSD-3-Clause
- `pdfplumber`：MIT
- `pdfminer.six`：MIT
- `pypdfium2`：Apache-2.0 or BSD-3-Clause
- vendored `PDF.js` assets：Apache-2.0

仓库主许可证仍然可以保持 MIT；第三方许可证说明见 [THIRD_PARTY_NOTICES.md](./THIRD_PARTY_NOTICES.md)。

## Prerequisites

需要先准备两样东西：

1. Python 3.12+
2. 可用的 `codex` 命令行，并且已经登录/配置完成

说明：

- Web app 自己会创建和使用仓库内的 `.venv`
- AI 能力默认通过本 repo 自带的本地 OpenAI-compatible bridge 转发到 `codex exec`
- 如果机器上没有可用的 `codex` 命令，界面仍可打开，但生成阅读导图和 AI chat 无法工作
- 如果你当前只有 Windows 商店版/桌面版 Codex，并且 bridge 报 `codex_not_executable` 或 `Access is denied`，通常需要把 `CODEX_BRIDGE_COMMAND` 指到一个可被脚本调用的独立 Codex CLI

## Setup

### 1. Create the repo-local virtual environment

Windows PowerShell:

```powershell
python -m venv .venv
```

如果你的 Python 在 Windows 上触发 `ensurepip` 临时目录权限问题，可以用这个回退方案：

```powershell
python -m venv --without-pip .venv
python -m pip --python .\.venv\Scripts\python.exe install pip
```

### 2. Install dependencies into this repo only

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 3. Start the app manually

```powershell
.\.venv\Scripts\python.exe run.py
```

如果你只是手动运行 `run.py`，那也需要另外启动本地 bridge：

```powershell
.\start_codex_bridge.cmd
```

## One-Click Start

Windows 资源管理器里直接双击：

```text
start_paper_reader.cmd
```

这个脚本会：

- 进入仓库根目录
- 检查并创建 repo-local `.venv`
- 必要时自动安装 `requirements.txt`
- 检查内建本地 bridge 是否已经可用
- 如果 bridge 未启动，则自动拉起 `start_codex_bridge.cmd`
- 启动应用
- 自动打开浏览器到 `http://127.0.0.1:8790`

这意味着默认情况下，你不需要先手动打开一个 bridge 窗口再回到应用里点击按钮。

### Standalone bridge start

如果你只想单独启动 bridge，也可以直接运行：

```text
start_codex_bridge.cmd
```

它会：

- 使用 repo-local `.venv`
- 读取本 repo 内的 bridge 脚本 `scripts/codex_bridge.py`
- 复用机器上的 `codex` 命令
- 在 `http://127.0.0.1:8765/v1` 提供本地 OpenAI-compatible API

## Local Bridge Configuration

应用默认把模型请求发到本地 bridge，可通过环境变量或页面顶部设置覆盖：

- `PAPER_READER_BRIDGE_URL`
- `PAPER_READER_MODEL`
- `PAPER_READER_API_KEY`
- `PAPER_READER_REASONING_EFFORT`
- `PAPER_READER_HOST`
- `PAPER_READER_PORT`

bridge 启动器本身还支持这些变量：

- `CODEX_BRIDGE_COMMAND`
- `CODEX_BRIDGE_HOST`
- `CODEX_BRIDGE_PORT`
- `CODEX_BRIDGE_WORKDIR`
- `CODEX_BRIDGE_DEFAULT_MODEL`
- `CODEX_BRIDGE_DEFAULT_REASONING_EFFORT`
- `CODEX_BRIDGE_API_TOKEN`
- `CODEX_BRIDGE_EXTRA_ARGS`

默认值：

- bridge URL: `http://127.0.0.1:8765/v1`
- model: `gpt-5.4-mini`
- reasoning effort: bridge/model default
- app host: `127.0.0.1`
- app port: `8790`

### Override file

如果你的 `codex` 不在默认 PATH，或者你想改 bridge 端口/默认模型，复制下面这个模板：

```text
scripts/codex_bridge.local.example.cmd
```

改名为：

```text
scripts/codex_bridge.local.cmd
```

`scripts/codex_bridge.local.cmd` 已经被 `.gitignore` 忽略，适合放你自己的本地配置。

`start_paper_reader.cmd` 和 `start_codex_bridge.cmd` 都会读取这份本地覆盖文件，因此改了端口或 `codex` 路径后不需要分别维护两套脚本。

如果 bridge 窗口提示 `codex_not_executable`，优先检查这里的 `CODEX_BRIDGE_COMMAND`，不要继续用当前被 Windows 拒绝执行的默认入口。

## Windows Codex CLI Troubleshooting

Windows 上最容易踩的坑是：系统里同时存在多个 `codex` 入口，但并不是每个入口都适合被 Python bridge 当作子进程调用。

推荐先在普通 `cmd.exe` 里检查：

```bat
codex --version
where codex
```

理想结果通常像这样：

```text
C:\Users\你的用户名\AppData\Roaming\npm\codex
C:\Users\你的用户名\AppData\Roaming\npm\codex.cmd
```

不太理想的结果通常像这样：

```text
C:\Program Files\WindowsApps\OpenAI.Codex_...\codex.exe
```

说明：

- `WindowsApps` 下的桌面版入口有时可以在交互终端里调用，但会在 bridge 的子进程场景里报 `Access is denied` / `codex_not_executable`
- `AppData\Roaming\npm\codex.cmd` 这类 npm shim 通常更适合作为 bridge 的真实执行入口
- 当前仓库的 `start_codex_bridge.cmd` 会自动优先选择 `where codex` 里非 `WindowsApps` 的结果，并优先选 `.cmd` / `.bat`

如果仍然选错，手动创建 `scripts/codex_bridge.local.cmd`：

```bat
@echo off
set "CODEX_BRIDGE_COMMAND=C:\Users\你的用户名\AppData\Roaming\npm\codex.cmd"
```

然后重新双击：

```text
start_paper_reader.cmd
```

如果你看到的是 `codex_not_executable`：

1. 在普通 `cmd.exe` 里重新确认 `where codex`
2. 优先选择非 `WindowsApps` 的结果
3. 把那个绝对路径写进 `scripts/codex_bridge.local.cmd`
4. 再重启 bridge 或整套应用

## Reasoning Effort

页面顶部提供单独的 `Reasoning` 配置，不需要把强度写进模型名里。

推荐用法：

- model: `gpt-5.4` 或 `gpt-5.4-mini`
- reasoning: `medium`
- 更难的论文问答或导图生成：`high`
- 如果你的 bridge 和模型支持，并且你愿意换更高时延/成本：`xhigh`

也可以直接在终端里预设：

```powershell
$env:PAPER_READER_MODEL="gpt-5.4"
$env:PAPER_READER_REASONING_EFFORT="high"
.\start_paper_reader.cmd
```

说明：

- 项目会把这个值透传为 `reasoning_effort`
- 如果留空，就交给 bridge 或模型默认行为
- 输入 `median` 时，项目会自动按 `medium` 处理

## Useful Flags

- `PAPER_READER_SKIP_BROWSER=1`
- `PAPER_READER_SKIP_BRIDGE=1`
- `PAPER_READER_DRY_RUN=1`

示例：

```powershell
$env:PAPER_READER_SKIP_BROWSER="1"
.\start_paper_reader.cmd
```

```powershell
$env:PAPER_READER_SKIP_BRIDGE="1"
.\start_paper_reader.cmd
```

## Project Structure

```text
paper-reader-agent/
├─ AGENTS.md
├─ README.md
├─ THIRD_PARTY_NOTICES.md
├─ requirements.txt
├─ run.py
├─ start_paper_reader.cmd
├─ start_codex_bridge.cmd
├─ data/
│  ├─ papers/
│  └─ exports/
│     └─ obsidian/
├─ scripts/
│  ├─ codex_bridge.py
│  └─ codex_bridge.local.example.cmd
├─ src/
│  └─ paper_reader_agent/
│     ├─ app.py
│     ├─ config.py
│     ├─ models.py
│     ├─ static/
│     │  ├─ app.css
│     │  └─ app.js
│     ├─ templates/
│     │  └─ index.html
│     └─ services/
│        ├─ bridge.py
│        ├─ context.py
│        ├─ library.py
│        ├─ obsidian.py
│        ├─ papers.py
│        └─ storage.py
└─ tests/
   └─ test_context.py
```

## Notes

- 不依赖其他仓库或全局环境里“刚好有”的包
- 默认不引入 Node 构建链；前端目前是纯静态资源
- 扫描论文目录时不会出现常驻论文库侧栏，而是通过顶部入口动作和选择器打开论文
- Obsidian 相关目录和导出 hint 已预留，但暂未开放正式导出按钮
