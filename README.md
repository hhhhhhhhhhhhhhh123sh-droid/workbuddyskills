# workbuddyskills

专供 **WorkBuddy** 使用的技能（Skill）库。每个技能一个子目录，目录内自带 `SKILL.md`（技能入口，Agent 读取）和 `README.md`（面向人的说明）。

Agent skills for [WorkBuddy](https://www.workbuddy.cn). One skill per subdirectory; each ships its own `SKILL.md` (the agent-facing entry point) and `README.md` (human-facing docs).

---

## 技能列表

| 技能 | 说明 |
|---|---|
| [`zotero-library-manager`](zotero-library-manager/) | 让 AI 助手直接读写本机 **Zotero 桌面版**文库：新建/整理分类、从 arXiv 导入论文并自动挂上 PDF 全文、给已有条目补挂附件、批量改字段、固定分类内排序、写中文导读笔记、全库体检（空标题/缺附件/文件丢失）、查重复条目。纯 Python 标准库，零依赖。 |

## 安装

把需要的技能目录复制到本机技能目录（Windows 下为 `%USERPROFILE%\.workbuddy\skills\`）：

```bash
git clone https://github.com/hhhhhhhhhhhhhhh123sh-droid/workbuddyskills.git

# 复制单个技能到本机技能目录
cp -r workbuddyskills/zotero-library-manager ~/.workbuddy/skills/
```

只想取某一个技能时，可用稀疏检出：

```bash
git clone --filter=blob:none --sparse https://github.com/hhhhhhhhhhhhhhh123sh-droid/workbuddyskills.git
cd workbuddyskills
git sparse-checkout set zotero-library-manager
```

装好后**新开一个会话**，Agent 会在可用技能列表里自动发现它。

## 目录约定

```
<技能名>/
├── SKILL.md       技能主文件（Agent 入口，必需，含 name / description 头部）
├── README.md      面向人的使用说明
├── LICENSE        许可
├── scripts/       可执行脚本
└── references/    按需加载的参考资料
```

## 许可

各技能目录内自带 `LICENSE`。`zotero-library-manager` 使用 MIT。
