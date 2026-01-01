# Project Context

## Purpose
医疗云影像下载器，支持从多个在线医疗影像平台下载CT、MRI等医学影像的DICOM文件。项目为患者提供便捷的影像获取途径，支持从各大医院和医疗云平台下载原始DICOM文件。

主要功能包括：
- 支持12+个主流医疗云平台（包括海纳医信、上海申康、中山医院、飞图影像等）
- 自动解析报告链接，智能识别目标平台
- 下载完整的DICOM文件结构，保持原始目录组织
- 支持JPEG2000无损压缩和原始像素格式
- 提供交互式和命令行两种使用方式

## Tech Stack
- **语言**: Python 3.8+
- **核心库**:
  - pydicom~3.0 - DICOM文件处理和解析
  - aiohttp~3.12 - 异步HTTP客户端
  - playwright~1.55 - 浏览器自动化和Web抓取
  - loguru~0.7 - 结构化日志记录
  - yarl~1.20 - URL解析和处理
  - pycryptodomex~3.23 - 加密解密功能
  - tqdm~4.67 - 进度条显示

- **开发依赖**:
  - pytest~8.4 - 单元测试框架
  - pylibjpeg系列 - DICOM图像编解码
  - numpy~2.3 - 数值计算
  - Pillow~11.3 - 图像处理

- **工具链**:
  - PyInstaller - 打包为可执行文件
  - Playwright - 浏览器驱动管理

## Project Conventions

### Code Style
- **注释**: 使用中文注释和日志，便于国内开发者理解
- **命名规范**: 
  - 模块名使用下划线分隔的小写字母（snake_case）
  - 类名使用首字母大写的驼峰命名（PascalCase）
  - 函数和变量名使用小写字母加下划线（snake_case）
- **编码标准**: 统一使用UTF-8编码
- **异步编程**: 广泛使用async/await模式处理网络I/O
- **错误处理**: 使用结构化日志记录错误信息，支持异常追踪

### Architecture Patterns
- **模块化下载器架构**: 每个医疗平台对应独立的下载器模块，位于`crawlers/`目录
- **抽象基类设计**: `PlaywrightCrawler`提供通用下载器功能，子类实现具体业务逻辑
- **工厂模式**: `downloader.py`根据URL自动选择对应的下载器模块
- **单例浏览器模式**: 全局浏览器实例管理，支持多页面复用
- **分层日志系统**: 统一的日志配置，支持控制台、文件、错误日志分离

### Testing Strategy
- **测试框架**: pytest，支持异步测试
- **测试配置**: 
  - `asyncio_mode = auto` - 自动处理异步测试
  - `asyncio_default_fixture_loop_scope = session` - 会话级别的事件循环
- **测试覆盖**: 
  - 单元测试覆盖工具函数和工具类
  - 手动测试验证下载器功能
  - 集成测试确保端到端流程正常
- **测试目录**: `test/`目录包含测试代码和测试数据

### Git Workflow
- **分支策略**: 基于主干的开发模式
- **提交规范**: 使用清晰的提交信息描述功能或修复
- **代码审查**: 通过PR进行代码审查
- **版本管理**: 语义化版本号管理

## Domain Context
**医疗影像学领域**:
- DICOM（Digital Imaging and Communications in Medicine）标准：医学数字成像和通信标准
- 医疗影像类型：CT、MRI、X光、超声等医学影像
- 影像存储格式：支持JPEG2000压缩和原始像素数据
- 医疗机构系统：各大医院使用的不同医疗云平台和PACS系统

**支持的医疗平台**:
- 海纳医信medicalimagecloud.com系列
- 地方卫健委平台（如重庆12320）
- 医院自建平台（如中山医院、第四军医大学）
- 第三方医疗云服务商（如飞图影像、远程影像云）

**合规考虑**:
- 仅用于个人医疗影像获取
- 尊重各平台的访问权限和使用条款
- 不进行批量或商业化下载

## Important Constraints
- **反爬机制**: 各医疗平台有不同程度的反爬措施，需要模拟真实用户行为
- **浏览器依赖**: 部分平台必须使用浏览器访问，依赖Playwright或系统浏览器
- **时效性**: 医疗报告链接通常有时效性，过期后无法访问
- **兼容性**: 需要适配不同平台的URL格式和页面结构
- **数据完整性**: 必须确保下载的DICOM文件完整性和可用性
- **平台限制**: 部分平台不支持原始文件下载（如锐珂、联众医疗等）

## Temporary File Management
- **tmp/目录规范**: 所有临时测试文件、验证脚本和临时文档必须存放在项目根目录的`tmp/`文件夹中
- **文件类型**: 包括但不限于：
  - 临时测试脚本（如test_*.py、*_test.py）
  - 数据验证脚本（如validate_*.py、analyze_*.py）
  - 临时文档和修复报告（如*_SUMMARY.md、*_FIX_*.md）
  - 调试和诊断工具脚本
- **清理原则**: tmp/目录中的文件属于开发过程中的临时产物，应定期清理
- **命名规范**: 临时文件应使用描述性的名称，并在文件名中体现其临时性质
- **版本控制**: tmp/目录应包含在.gitignore中，不纳入版本控制
- **示例**: 
  - `tmp/test_dicom_fix.py` - DICOM修复功能测试脚本
  - `tmp/DICOM_FIX_SUMMARY.md` - DICOM修复总结报告
  - `tmp/validate_files.py` - 文件验证工具

## External Dependencies
**医疗云平台API**:
- medicalimagecloud.com - 海纳医信云影像平台
- mdmis.cq12320.cn - 重庆卫健委在线报告平台
- ylyyx.shdc.org.cn - 上海申康医院发展中心影像平台
- zscloud.zs-hospital.sh.cn - 复旦大学附属中山医院影像平台
- ftimage.cn - 飞图影像医疗云平台
- qr.szjudianyun.com - 深圳聚点云平台
- mtywcloud.com - 明天医网平台
- yzhcloud.com - 远程影像云平台
- work.sugh.net - 上航院平台
- 其他医院专属平台

**浏览器和驱动**:
- Chromium/Chrome浏览器（通过Playwright管理）
- Microsoft Edge（Windows平台备用选项）
- Playwright浏览器驱动

**第三方服务**:
- 医疗云平台的WebSocket实时通信
- HTTP/HTTPS网络请求
- 文件系统和存储服务

## 环境配置要求
**推荐使用Conda环境**:
```bash
# 创建专用环境
conda create -n dicom python=3.8
conda activate dicom

# 安装依赖
conda install -n dicom -c conda-forge pyinstaller
# 或者在环境激活后使用 pip
conda run -n dicom pip install -r requirements.txt

# 运行程序
conda run -n dicom python downloader.py <url>

# 打包为可执行文件
conda run -n dicom pyinstaller --onefile --name cloud-dicom-downloader downloader.py
```

**Python环境要求**:
- Python 3.8+
- 所有依赖通过`requirements.txt`统一管理
- 开发依赖通过`requirements-dev.txt`管理
