# 稍后听 · Listen Later

把收藏的内容变成双人播客和图文精华，保留原始信源与视频时间点。

## 先看效果

解压后直接打开 **试听.html**，即可播放预制节目和查看图文；无需 Python、密钥或本地服务。原访谈等外部链接需要网络。

要体验完整收藏与制作界面，需要 Python 3.9+ 和首次安装依赖时的网络。在本文件所在目录运行：

```sh
python3 scripts/manage.py setup
python3 scripts/manage.py demo
```

打开命令返回的地址，即可体验一段 2 分 46 秒的预制双人节目、三章图文精华和原访谈跳转。预制示例不消耗模型或语音额度，也不需要登录内容平台。

## 在 Codex 里使用

如果已安装 Git，可直接克隆到 Skill 目录：

```sh
git clone https://github.com/chloe050918/listen-later.git ~/.codex/skills/listen-later
```

若目标目录已存在，请先保留原版本，不要直接覆盖。


将整个 `listen-later` 文件夹放到 `~/.codex/skills/`，重新打开会话后说：

> 用 $listen-later 先检查环境，再打开预制示例。我想体验播放、图文笔记和溯源。

要用自己的内容生成：先按 [配置说明](references/setup.md) 填写自己的模型与语音服务凭证，再说：

> 用 $listen-later 把这些内容做成一期两分钟双人播客，审稿后生成音频和图文精华，并验证结果。

可以先用附带的自编练习 `examples/materials.json`，排除平台登录对首次使用的影响。

## 使用条件

- 生成新节目需要用户自己的火山方舟、火山语音权限及额度，以及 ffmpeg。包内没有共享密钥。
- 来源访问取决于用户网络、登录与宿主浏览器能力；正文粘贴和字幕导入可独立使用。
- 图文与播客链接仅在运行服务的电脑上可用。定时任务由宿主另外配置，安装不会自动创建任务。
- 已在 macOS 隔离目录和全新虚拟环境完成真实生成验证；不承诺未经实测的 Windows、Linux 或其他 Agent 宿主兼容性。

[验收记录与已知边界](verification.md)
