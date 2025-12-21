## ADDED Requirements

### Requirement: 合并 xa_data 爬虫模块
The xa_data crawler module SHALL be merged with its helper functions from xa_helpers.py into a single independent file.

#### Scenario: 合并 xa_data.py 和 xa_helpers.py
Given xa_data.py 依赖 xa_helpers.py 中的辅助函数
When 将 xa_helpers.py 的内容合并到 xa_data.py 中
Then xa_data.py 成为独立的文件，包含所有必要函数
And 保持统一的 run 接口
And 符合项目代码风格和架构约定

### Requirement: 清理冗余文件
The redundant xa_helpers.py file SHALL be removed after merging its contents.

#### Scenario: 移除 xa_helpers.py 文件
Given xa_helpers.py 的内容已合并到 xa_data.py
When 删除 xa_helpers.py 文件
Then crawlers 目录只包含独立的医院爬虫模块
And 每个医院对应一个文件