# Merge xa-data Helpers

## Why
xa_data.py 爬虫模块依赖 xa_helpers.py 中的辅助函数，导致代码分散在两个文件中。这与项目架构约定不符：每个医院爬虫应该是一个独立的模块文件。

## What Changes
- 将 xa_helpers.py 中的 normalize_images_field、fetch_image_bytes、build_minimal_tags 函数合并到 xa_data.py
- 删除 xa_helpers.py 文件
- 优化 xa_data.py 的导入语句，符合 PEP 8 标准

## Summary
将 `crawlers/xa_data.py` 和其依赖的 `crawlers/xa_helpers.py` 合并为一个文件 `crawlers/xa_data.py`，保持与其他医院爬虫脚本的结构一致，实现统一的 run 接口，并符合项目的代码风格和架构约定。

## Motivation
- 简化代码结构，减少文件数量
- 保持与其他爬虫模块的一致性（每个医院一个文件）
- 符合项目约定：模块化爬虫架构，每个平台独立模块

## Impact
- 无功能变更，仅重构代码组织
- 确保代码符合项目风格和架构
- 维护统一的 run 接口