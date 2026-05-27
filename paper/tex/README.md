# IEEE Transactions LaTeX 稿件

> 投稿目标：**IEEE Transactions on Industrial Informatics**（PVEL-AD 数据集自身发表的期刊，对标顶刊）
>
> 文档类：`IEEEtran.cls`（journal mode）
>
> 当前预设：单栏 11pt 草稿模式 → 投稿前一行切换为双栏 10pt

---

## 文件清单

```
paper/tex/
├── main.tex          ← 主文档（约 6000 词，IMRaD 完整 5 节 + 摘要）
├── refs.bib          ← 30 条 BibTeX 参考文献（顶级会议/期刊）
├── figures/          ← 图占位目录（实验完成后由 code/paper/figures 拷入）
└── README.md         ← 本文件
```

## 编译方式

### 方式 A：本地 TeX Live / MiKTeX

```cmd
cd E:\Users\Administrator\Desktop\gp\graduation_project\paper\tex
pdflatex main
bibtex main
pdflatex main
pdflatex main
```

第三次 pdflatex 是为了让正文中所有的 `\ref{}` 与 `\cite{}` 都正确解析。

### 方式 B：Overleaf（推荐，零配置）

1. 打开 [overleaf.com](https://www.overleaf.com/) 注册免费账号
2. New Project → Upload Project → 把整个 `paper/tex/` 文件夹打包成 zip 上传
3. 主文件选 `main.tex`，编译器选 `pdfLaTeX`，TeX Live 版本 `2024`
4. 点 Recompile 即可生成 PDF

---

## 投稿前必做的样式切换

`main.tex` 第 11 行：

```latex
\documentclass[journal,onecolumn,11pt]{IEEEtran}   % ← 现在是草稿模式
```

投稿时改为：

```latex
\documentclass[journal]{IEEEtran}                  % ← IEEE 双栏标准
```

这一行改完后会自动切到双栏 10pt 标准 IEEE 论文样式（约 10 页）。

---

## 论文结构（已落地）

| 节 | 内容 | 状态 |
|---|---|---|
| Abstract + IndexTerms | 250 词中英摘要 | ✅ 数字占位 |
| I. Introduction | 背景 → 三大挑战 → 三项贡献 → 论文组织 | ✅ 完整 |
| II. Related Work | 通用检测 / PV 检测 / 注意力 / 多尺度融合 | ✅ 完整 |
| III. Methodology | 数据集 + 网络架构 + 训练协议 | ✅ 完整 |
| IV. Experiments | Baseline / Ablation / Complexity / Robustness / Visualization / Deployment / Discussion | 🟡 数字占位 |
| V. Conclusion | 工作总结 + 5 项 limitations + future work | ✅ 完整 |
| References | 30 条 BibTeX | ✅ 完整 |

---

## 待填占位（自动用宏替换）

`main.tex` 中的所有占位都用了 LaTeX 宏：

```latex
\newcommand{\TBF}[1]{\textcolor{red}{\textbf{[TBF: #1]}}}
\newcommand{\mAPHalf}{\TBF{mAP@0.5}}
\newcommand{\mAPFull}{\TBF{mAP@0.5:0.95}}
...
```

实验跑完后，**把这些宏的定义改成具体数字**，整篇论文的所有引用位置一次更新。例如：

```latex
\newcommand{\mAPHalf}{0.8542}    % 替换占位
\newcommand{\paramsM}{3.1}
\newcommand{\fpsVal}{142}
```

红色 [TBF: ...] 标记会全部消失，论文就能投稿。

---

## 待补充的内容

| 项 | 说明 |
|---|---|
| 作者信息 | 第 31 行 `\author{...}` 改成你的姓名 / 学校 / 邮箱 |
| 所有 `\TBF{}` 占位 | 实验完成后用真实数字替换 |
| `figures/` 目录 | 把 `code/paper/figures/*.png` 拷过来 |
| Table II 消融数据 | 5 行 ablation 数字 |
| 图 4 鲁棒性曲线 | `fig_robustness.png` |
| 图 5 Grad-CAM | `fig_grad_cam.png` |
| 图 6 检测对比 | `fig_qualitative.png` |
| `refs.bib` 中标 `note = {... to be verified ...}` 的条目 | 用 Semantic Scholar / Google Scholar 校验 |

---

## 与中文毕设的关系

`paper/01_introduction.md` ~ `paper/05_conclusion.md` 是**中文毕业论文版本**（约 22 000 字，IMRaD 内核 + 学校规范）。

`paper/tex/main.tex` 是**英文期刊投稿版本**（约 6000 词，IEEE TII 风格）。

二者**互为对照**：
- 中文版写得详尽，方法 + 实验 + 讨论各章扩展，适合答辩 / 学位论文
- 英文版精炼，按顶级期刊体例严格组织，适合投稿

实验完成后我会**同步更新两份**：把数字 patch 进去、再交叉检查 metric 表述一致。

---

## 投稿前最终 checklist

- [ ] 所有 `\TBF{}` 已替换为真实数字
- [ ] 切换到双栏：`\documentclass[journal]{IEEEtran}`
- [ ] 作者信息已填
- [ ] 所有 figure 已生成并拷贝到 `tex/figures/`
- [ ] `bibtex` 编译无 warning（每条引用都正确解析）
- [ ] PDF 页数 ≤ IEEE TII 上限（regular paper 14 页）
- [ ] 致谢段中包含资助来源（如有）
- [ ] 自查英文表达：用 Grammarly / DeepL Write 过一遍
