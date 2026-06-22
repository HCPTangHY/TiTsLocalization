# TiTs Localization

Localization framework for Trials in Tainted Space (TiTS).

## 目录结构

```
├── src/                          # 工具脚本
│   ├── pipeline.py               # 统一入口
│   ├── splitter.py               # webpack chunk 拆分器
│   ├── scanner.py                # JS 游标扫描器
│   ├── rules.py                  # 词条提取规则
│   ├── replacer.py               # POS 替换器
│   └── util.py                   # 工具函数
├── source/<version>/             # 原始 JS 文件（不入库）
├── split/<version>/              # 拆分后的子模块（不入库）
├── pz_origin/<version>/          # 提取的词条 JSON（上传 ParaTranz）
├── trans_origin/<version>/       # 翻译后的词条 JSON（从 ParaTranz 下载）
└── dist/<version>/               # 替换后的 JS 文件（不入库）
```

## 使用方法

### 1. 准备源文件

将游戏的 JS 文件放到 `source/<version>/` 目录下：

```bash
mkdir -p source/0.9.159
cp /path/to/game/main.*.js source/0.9.159/
cp /path/to/game/content_*.js source/0.9.159/
```

### 2. 提取词条

```bash
python src/pipeline.py -v 0.9.159 all
```

### 3. 翻译

将 `pz_origin/<version>/` 上传到 ParaTranz。翻译完成后下载到 `trans_origin/<version>/`。

### 4. 回写

```bash
python src/pipeline.py -v 0.9.159 replace
```

产出在 `dist/<version>/`。
