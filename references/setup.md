# 安装与试用

## 安装到 Codex

解压整个 `listen-later` 文件夹，放入 `~/.codex/skills/`，确认路径为 `~/.codex/skills/listen-later/SKILL.md`。如同名目录已存在，先保留旧版本，勿直接覆盖数据。重新打开会话后使用 `$listen-later`；如果宿主没有发现它，可先让 Agent 读取该文件。

Windows 的 `~` 指用户目录，命令中的 Python 可替换为 `py -3`。Windows、Linux、WorkBuddy 的实际安装与运行尚未验证，不能据此承诺即装即用。

## 两种试用路径

### 只体验产品

直接打开包内 `试听.html` 可免安装体验预制节目。要使用完整本地网页，在 Skill 目录运行：

```sh
python3 scripts/manage.py setup
python3 scripts/manage.py demo
```

第一条需联网下载 Python 依赖，按随包锁定版本安装；第二条不调用模型和语音服务。打开返回地址即可播放预制节目、看图文、点击原访谈时间点。外部来源页面仍需相应网络。示例不会自动导入为待制作收藏。

### 制作自己的第一期

1. 安装 Python 3.9+。推荐 Python 3.11 或更新的受支持版本。当前隔离测试使用 macOS Python 3.9.6；系统 Python 可能提示 SSL 库兼容警告，不能据此推定其他机器的网络兼容性。
2. 安装 ffmpeg，确认终端能运行 `ffmpeg -version` 和 `ffprobe -version`。程序不自动改系统或安装系统软件。
3. 执行 `setup` 后，打开 `doctor` 输出的配置路径。填入自己的 `ARK_API_KEY`、`ARK_CHAT_MODEL`、`VOLC_SPEECH_API_KEY`，以及 `VOLC_VOICE_HOST_A`、`VOLC_VOICE_HOST_B`。两种音色必须不同，并已向该账号开放。所填方舟模型需支持聊天接口；读图还需视觉能力。
4. 执行 `doctor --production`。字段齐全不等于账号权限或余额已验证。
5. 为避免登录和抓取影响首次体验，先用附带的 `examples/materials.json` 自编文本做一分钟练习：

```sh
python3 scripts/manage.py import --input examples/materials.json
python3 scripts/manage.py prepare --seconds 60 --wait 50
```

取得稿件后由 Agent 对照材料审阅，再调用 finish。用户自己的素材随后通过网页或 import 加入。自编练习不能说成来自外部文章。

文本编排和语音合成会调用用户自己的付费服务。账号、模型与音色权限不随 Skill 分发；本包不提供共享密钥。网络故障、额度不足、平台登录或抓取限制仍可能发生，失败不会标成完成。

## 文件与端口

- `.venv` 在包目录内；用户数据、稿件、音频在 `~/.listen-later`，不随更新包覆盖。
- 配置默认在数据目录下 `.env`；可通过 `LISTEN_LATER_ENV` 指定另一个本机文件，环境变量优先。
- 默认从 8770 起寻找可用端口，保存到数据目录 `runtime.json`。明确设置 `LISTEN_LATER_PORT` 时不会自动换端口。
- 同一用户的数据目录避免被多台设备并发写入；多个独立实例各自使用不同数据目录和端口。
- 无公网托管、RSS 或手机远程访问。不把作者的 localhost 链接发给面试官当作远程试用地址，应发送完整分发包。
