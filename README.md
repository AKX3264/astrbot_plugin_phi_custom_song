# Phigros 猜歌插件 (astrbot_plugin_phi_guess)

## 📖 简介

基于 Lilith 开放平台 API 的 Phigros 猜歌 / 抽歌插件，配合 [astrbot_plugin_phi_custom](https://github.com/AKX3264/astrbot_plugin_phi_custom)（查分插件）使用，**共享别名库**。

功能包括：
- 遮罩猜歌：随机出 10 首歌，名字用 `*` 遮住，用编号提交答案
- 随机抽歌：按难度 / 等级筛选后随机抽一首
- 积分排行：按群统计猜对次数
- 别名匹配：输入别名（如「痉挛」）也能匹配到正式歌名

## 🎮 指令列表

| 指令 | 说明 | 权限 |
| :--- | :--- | :--- |
| `/猜歌` | 显示猜歌模块帮助 / 当前进度 | 所有人 |
| `/猜歌 开始` | 开始一轮猜歌（10 首） | 所有人 |
| `/猜歌 开<n>` | 随机揭开 n 个字符 | 所有人 |
| `/猜歌 <编号> <曲名>` | 猜某序号是什么歌（支持别名） | 所有人 |
| `/猜歌 结束` | 强制结束本轮（需回复"确认"二次确认） | 所有人 |
| `/猜歌 rank` | 查看本群猜歌排行榜 | 所有人 |
| `/猜歌 help` | 详细玩法 | 所有人 |
| `/随机选歌` | 从 IN 难度随机选一首 | 所有人 |
| `/随机选歌 <难度>` | 从指定难度随机选（EZ / HD / IN / AT） | 所有人 |
| `/随机选歌 <难度> <等级>` | 按难度 + 等级筛选，如 `/随机选歌 AT 16.5` | 所有人 |
| `/随机选歌 <等级>` | 只填等级，默认按 IN 难度筛选 | 所有人 |

> **说明**：等级匹配容差 0.05，输入 `15.5` 能匹配定数 15.5。

## 🎯 玩法示例

```
/猜歌 开始
━━━━━━━━━━━━━━━━
📋 猜歌列表（10 首）
━━━━━━━━━━━━━━━━
1. S*********c
2. ***********
3. *********
4. C**** S***
5. ぱぴぷぴぷぴぱ
6. I****** E*****
7. ********
8. ******
9. *******
10. *********
━━━━━━━━━━━━━━━━
📊 进度：0/10

/猜歌 3 Spasmodic
✅ 你 猜对了！
🎵 3. **Spasmodic**

/猜歌 1 痉挛          ← 用别名也能猜
✅ 你 猜对了！
🎵 1. **Spasmodic**

/猜歌 开2              ← 随机揭开 2 个字符
🔓 已随机揭开 2 个字符：
  4. C
  6. I
...

/猜歌 rank
🏆 猜歌排行榜
━━━━━━━━━━━━━━━━
🥇 3463271706：15 分
🥈 1234567890：8 分

/猜歌 结束
⚠️ 确认要结束本轮猜歌吗？
回复 确认 立即结束。

确认
🛑 本轮猜歌已结束。
```

## 🏷️ 别名库共享

本插件会**自动读取查分插件的别名库**，让猜歌也支持别名输入。

**查找顺序**：
1. 优先读取 `astrbot_plugin_phi_custom/data/aliases.json`（用户改动后的最新别名库）
2. 兜底读取 `astrbot_plugin_phi_custom/default_aliases.json`（默认别名库）

**前提条件**：
- 两个插件必须放在**同一个 plugins 目录**下（即 `core/data/plugins/`）
- 目录名必须是 `astrbot_plugin_phi_guess` 和 `astrbot_plugin_phi_custom`

**别名效果**：
- 用户猜 `痉挛`，插件会自动解析成 `Spasmodic` 再匹配
- 每次 `/猜歌 开始` 前会自动刷新一次别名库，保证拿到最新改动

## ⚙️ 配置项说明

| 配置项 | 主标题 | 说明 | 类型 | 默认值 |
| :--- | :--- | :--- | :--- | :--- |
| `lilith_api_key` | Lilith API Key | 请前往 https://lilith.xtower.site/open-platform 使用 GitHub 登录，创建 API Key 并复制以 `pgr_live_` 开头的密钥。 | string (secret) | 空 |
| `phi_api_url` | API 基础地址 | Lilith API 基础地址，末尾不要带斜杠或路径。 | string | `https://r0semi.xtower.site` |
| `proxy_url` | 网络代理地址 | 可选。如 `http://127.0.0.1:7890`。 | string | 空 |
| `timeout` | 请求超时时间（秒） | 范围 5-120。 | int | `30` |

## 🔧 依赖安装说明

本插件依赖分两类：

| # | 类别 | 内容 | 是否必装 |
| :--- | :--- | :--- | :--- |
| 一 | Python 库（pip） | `httpx`、`Pillow` | **必装** |
| 二 | 系统组件 | Playwright Chromium | 可选（仅发送曲绘时用到） |

### 一、Python 库（pip，必装）

插件启动时会自动检测并安装缺失的 pip 库（清华源）。如自动失败，请手动安装：

**方法 A：AstrBot WebUI**
1. 打开 **平台日志** 页面
2. 点右上角 **「安装 Pip 库」**
3. 库名填：`httpx Pillow`
4. 强制 PyPI 源填：`https://pypi.tuna.tsinghua.edu.cn/simple`
5. 安装后**完全重启** AstrBot

**方法 B：命令行**

```cmd
cd C:\Users\Administrator\.astrbot_launcher\instances\<实例ID>\venv\Scripts
activate
pip install httpx Pillow -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 二、Playwright Chromium（可选）

猜歌和随机选歌的**主要功能是文本**，不依赖 Playwright。但猜对后揭晓的**曲绘图片**会用到图片发送功能，如果 NapCat 的 Rkey 正常，可以直接发本地文件，不一定要 Playwright。

**如果你已经装了查分插件（astrbot_plugin_phi_custom），Playwright 应该已经装好，可以跳过这一步。**

如果没有，参考查分插件 README 里的 Playwright 安装章节，或者在 AstrBot 的 Python 环境执行：

```cmd
playwright install chromium
```

国内网络慢先设镜像：

```cmd
set PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright
playwright install chromium
```

## 📁 文件结构

```
astrbot_plugin_phi_guess/
├── main.py
├── metadata.yaml
├── requirements.txt
├── _conf_schema.json
├── README.md
├── logo.png
└── data/                      # 运行时生成（.gitignore 忽略）
    ├── guess_scores.json      # 各群积分记录
    └── song_pool.json         # 歌曲池缓存
```

## 📌 注意事项

1. **配套使用**：建议和 [astrbot_plugin_phi_custom](https://github.com/AKX3264/astrbot_plugin_phi_custom) 一起装，猜歌才能用别名。
2. **API Key 共用**：两个插件用同一个 Lilith API Key 即可。
3. **歌曲池缓存**：首次启动会拉取并缓存全部歌曲到 `data/song_pool.json`，后续直接用缓存。如需刷新，删掉该文件重启。
4. **积分持久化**：猜对次数保存在 `data/guess_scores.json`，按群独立统计。
5. **API 域名**：所有请求发往 `https://r0semi.xtower.site`。

*本文档适用于插件版本 v1.0.0 及以上。*