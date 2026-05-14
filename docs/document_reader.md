# 文件读取器

创建虚拟分身时，用户可以上传 PDF、Word、PPT、Excel、TXT、Markdown、HTML、图片、截图、代码和日志等资料。

读取器输出统一 bundle：

- `document.md`
- `blocks.json`
- `provenance.json`
- `diagnostics.json`

默认链路：

1. 文本、代码、CSV、HTML 走轻量解析。
2. 数字 PDF、Office 文档先走 Docling。
3. 扫描 PDF、图片、复杂截图可启用 Marker/Surya OCR/VLM worker。

增强 OCR/VLM 运行时不会进入 Git。部署者应在自己的机器上安装并缓存模型。

检查后端：

```bash
uv run python scripts/document_reader/check_backends.py
```

运行小型 benchmark：

```bash
uv run python scripts/document_reader/run_fixture_benchmark.py --suite smoke
```

