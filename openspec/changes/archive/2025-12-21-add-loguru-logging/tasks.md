## 1. 项目准备
- [ ] 1.1 在项目根目录创建logs文件夹
- [ ] 1.2 将loguru添加到requirements.txt依赖列表

## 2. 创建日志配置模块
- [ ] 2.1 创建统一的日志配置模块
- [ ] 2.2 配置日志格式、级别和输出目标（文件+控制台）
- [ ] 2.3 设置日志轮转和保留策略

## 3. 更新核心脚本
- [ ] 3.1 更新downloader.py集成日志
- [ ] 3.2 更新check_eos_geometry.py集成日志

## 4. 更新爬虫模块
- [ ] 4.1 更新crawlers/_browser.py集成日志
- [ ] 4.2 更新crawlers/_utils.py集成日志
- [ ] 4.3 更新crawlers/cq12320.py集成日志
- [ ] 4.4 更新crawlers/ftimage.py集成日志
- [ ] 4.5 更新crawlers/hinacom.py集成日志
- [ ] 4.6 更新crawlers/jdyfy.py集成日志
- [ ] 4.7 更新crawlers/mtywcloud.py集成日志
- [ ] 4.8 更新crawlers/shdc.py集成日志
- [ ] 4.9 更新crawlers/sugh.py集成日志
- [ ] 4.10 更新crawlers/szjudianyun.py集成日志
- [ ] 4.11 更新crawlers/tdcloud.py集成日志
- [ ] 4.12 更新crawlers/xa_data.py集成日志
- [ ] 4.13 更新crawlers/yzhcloud.py集成日志
- [ ] 4.14 更新crawlers/zscloud.py集成日志

## 5. 更新工具脚本
- [ ] 5.1 更新tools/validate_dicom.py集成日志
- [ ] 5.2 更新tools/convert_jp2_to_j2k.py集成日志
- [ ] 5.3 更新tools/export.py集成日志
- [ ] 5.4 更新tools/manual.py集成日志
- [ ] 5.5 更新tools/mutate.py集成日志
- [ ] 5.6 更新tools/check_radiant_compat.py集成日志

## 6. 更新测试脚本
- [ ] 6.1 更新test/test_manual.py集成日志
- [ ] 6.2 更新test/test_utils.py集成日志

## 7. 测试验证
- [ ] 7.1 运行核心脚本验证日志输出正常
- [ ] 7.2 运行爬虫模块验证日志输出正常
- [ ] 7.3 运行工具脚本验证日志输出正常
- [ ] 7.4 检查logs目录下的日志文件生成
- [ ] 7.5 验证关键操作和异常都被正确记录</content>
</xai:function_call name="write_to_file">
<parameter name="path">openspec/changes/add-loguru-logging/specs/logging/spec.md