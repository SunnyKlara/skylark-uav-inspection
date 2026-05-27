# 数据集放哪里 / 怎么放

> 一句话：原始解压目录丢到 `code/data/raw/pvel_ad/`，剩下让脚本干。

---

## 标准目录

```
code/
└── data/
    ├── raw/                    ← 你手动放原始数据
    │   ├── pvel_ad.zip         （任选其一）官方 zip 改名放这
    │   └── pvel_ad/            （任选其一）解压后的目录直接放这
    │       ├── Annotations/    PVEL-AD 原始的 VOC xml
    │       ├── JPEGImages/     原始 jpg
    │       └── ...
    │
    └── processed/              ← 自动生成，别手动改
        └── pvel_yolo/
            ├── images/
            │   ├── train/
            │   ├── val/
            │   └── test/
            ├── labels/
            │   ├── train/
            │   ├── val/
            │   └── test/
            └── data.yaml       ← ultralytics 用的配置
```

`prepare_pvel_ad.py` 兼容三种放置:

| 你的输入                              | 脚本怎么处理                |
|-------------------------------------|----------------------------|
| `data/raw/pvel_ad.zip`              | 自动解压到 `data/raw/pvel_ad/` |
| `data/raw/pvel_ad/` 里有 .xml + .jpg | VOC → YOLO 转换 + 8:1:1 划分 |
| `data/raw/pvel_ad/` 里已经是 YOLO 格式 | 直接拷贝整理               |

---

## PVEL-AD 真实下载渠道

PVEL-AD 是 12 类（finger / crack / black_core / thick_line / horizontal_dislocation / short_circuit / vertical_dislocation / star_crack / printing_error / corner / fragment / scratch）共 36,543 张近红外图，原始格式是 PASCAL VOC（xml）。

**没有公开 Kaggle 数据集页**。常见的 `qianbinghui/pvel-ad` 链接是错的。

按推荐度排序：

### 渠道 1（首选）：Google Drive

作者 2026-01 公开的网盘链接（需梯子）：

- https://drive.google.com/drive/folders/1AMlo433v-torspIxynzx0wXGced8Eo3q

下载所有文件，解压到 `data/raw/pvel_ad/`。

### 渠道 2：邮件申请

- 仓库主页：https://github.com/binyisu/PVEL-AD
- 下载里面的 `Industrial_Data_Access_Form.docx`，**手写签字**，扫描成 PDF
- 用**学校域名邮箱**发到 `subinyi@vip.qq.com`（QQ / Gmail 邮箱会被拒）
- 通常 2 周内回复并发网盘链接

### 渠道 3：Kaggle 比赛页

- https://www.kaggle.com/competitions/pvelad
- 注册并加入比赛 → 下载数据
- 注意：test 集标注 2024 年才公开

### 渠道 4（备选 / 跑通流水线用）：Roboflow Universe

如果上面都搞不定，先用 Roboflow 上类似数据集走通流水线，最后再换正版数据集重训。

- https://universe.roboflow.com/
- 搜 `photovoltaic defect` / `solar panel defect` / `solar cell EL`
- 选一个数据量 > 1000 的 → Download → YOLOv8 / YOLOv11 格式 → 下 zip
- 解压后整体放到 `data/raw/pvel_ad/`（脚本自动识别 YOLO 格式）

---

## 验证你放对了

激活环境（`E:\conda_envs\yolo`），到 `code/` 目录下跑：

```cmd
python data\prepare_pvel_ad.py --dry-run
```

期望输出包含：

```
[OK] 已发现解压数据: ...\data\raw\pvel_ad
==> 检测到数据集格式: voc        # 或 yolo
[OK] dry-run 模式，仅检测路径与格式
```

如果显示 `[!!] 没有找到 PVEL-AD 数据`，就是路径放错了，对照上面目录树检查。

---

## 磁盘占用估算

| 阶段                       | 占用     |
|---------------------------|---------|
| 原始 zip                  | ~6 GB   |
| 解压后                    | ~12 GB  |
| 转 YOLO 格式（图复制一份）   | ~12 GB  |
| 训练日志 + 权重（全套跑完）   | ~8 GB   |
| **合计**                  | **~38 GB** |

如果 E 盘空间紧张，可以在转完 YOLO 格式后删 `data/raw/`。
