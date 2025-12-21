# 项目上下文

## Purpose
cloud-dicom-downloader 是一个医疗云影像下载器，用于从各种在线医疗报告平台下载 DICOM 文件，包括 CT、MRI 等医疗影像片子。支持多个国内医疗云平台，如 hinacom、ftimage、szjudianyun 等，便于患者或医生获取原始影像数据进行离线查看或分析。

## 技术栈
- Python 3.8+
- asyncio (异步编程)
- aiohttp~=3.12 (异步HTTP客户端)
- playwright~=1.55 (浏览器自动化)
- tqdm~=4.67 (进度条显示)
- yarl~=1.20 (URL处理)
- pycryptodomex~=3.23 (加密算法)
- pydicom~=3.0 (DICOM文件处理)

## 项目约定

### 代码风格
- 使用 Black 代码格式化工具
- 遵循 PEP 8 命名约定（snake_case）和导入风格
- 异步函数使用 async/await 语法
- 避免单行注释，优先使用有意义的变量名和函数名

### 架构模式
- 模块化爬虫架构：每个医疗云平台独立一个模块，实现统一的 run 接口
- crawlers 目录：存放不同医院的爬取脚本，每个医院对应一个独立的爬虫模块
- 异步并发下载：使用 asyncio 和 aiohttp 实现高效并发
- 浏览器自动化：对于需要JavaScript渲染的页面使用 playwright
- DICOM处理：自动生成符合标准的DICOM文件，包括必需的元数据标签
- 错误处理：完善的异常处理和重试机制，确保下载稳定性

### 测试策略
- 使用 pytest 作为测试框架
- 单元测试优先，覆盖核心爬虫逻辑
- 集成测试验证端到端下载流程
- 手动测试用于验证实际网站兼容性

### Git 工作流
- 主分支：main（稳定版本）
- 开发分支：dev（开发版本）
- 功能分支：feature/xxx（新功能）
- 提交信息：使用英文，遵循 Conventional Commits 格式

## 领域上下文
- 医疗影像：CT、MRI、X光等检查类型
- DICOM标准：医疗影像文件格式和元数据
- PACS系统：影像存储和传输系统
- 云医疗平台：在线影像阅片和报告系统

## 重要约束
- HIPAA/隐私保护：不得泄露患者个人信息
- 数据安全：仅下载授权访问的影像数据
- 合规性：遵守医疗数据传输法规
- 技术限制：部分系统不支持原始文件下载

## 外部依赖
- 医疗云平台API：
  - hinacom (海南医学会云平台)
  - ftimage (复旦天坛影像云平台)
  - szjudianyun (深圳聚点云平台)
  - cq12320 (重庆12320云平台)
  - shdc (上海东方云平台)
  - zscloud (中山云平台)
  - mtywcloud (绵阳天纬云平台)
  - yzhcloud (扬州华云平台)
  - sugh (苏州高新云平台)
  - jdyfy (金蝶云平台)
  - tdcloud (天地云平台)
  - xa_data (西安数据云平台)
- 浏览器自动化：playwright~=1.55（用于动态页面渲染和用户交互）
- 网络请求：aiohttp~=3.12（异步HTTP客户端，支持并发下载）

## 项目状态
- 当前版本：支持12个医疗云平台的DICOM下载
- 最新更新：修复DICOM文件生成，确保符合DICOM标准（SOPClassUID, SOPInstanceUID等必需标签）
- 代码重构：合并辅助模块，提升代码可维护性
- 测试验证：通过实际下载测试，验证DICOM文件有效性
