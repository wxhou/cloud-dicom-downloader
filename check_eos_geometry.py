import pydicom
import os
import sys
from tools.logging_config import get_logger

logger = get_logger(__name__)

def check_dicom_geometry(file_path):
    logger.info(f"开始检查DICOM几何信息: {os.path.basename(file_path)}")
    try:
        ds = pydicom.dcmread(file_path)
    except Exception as e:
        logger.error(f"读取DICOM文件失败: {file_path}, 错误: {str(e)}")
        return

    # 1. Check Standard Geometry Tags
    logger.info("[标准几何标签检查]")
    standard_tags = [
        (0x0018, 0x1110), # Distance Source to Detector
        (0x0018, 0x1111), # Distance Source to Patient
        (0x0018, 1114),   # Estimated Radiographic Magnification Factor
        (0x0018, 0x1510), # Positioner Primary Angle
        (0x0018, 0x1511), # Positioner Secondary Angle
        (0x0020, 0x0032), # Image Position (Patient)
        (0x0020, 0x0037), # Image Orientation (Patient)
        (0x0028, 0x0030), # Pixel Spacing
        (0x0018, 0x1164), # Imager Pixel Spacing
        (0x0008, 0x0070), # Manufacturer
        (0x0008, 0x1090), # Manufacturer's Model Name
    ]

    found_standard = False
    for tag_id in standard_tags:
        if tag_id in ds:
            elem = ds[tag_id]
            logger.info(f"{elem.name} ({elem.tag}): {elem.value}")
            found_standard = True
    
    if not found_standard:
        logger.warning("未找到标准几何标签")

    # 2. Search for Private Tags or Keywords
    logger.info("[私有标签和几何关键字搜索]")
    keywords = ["EOS", "Geometry", "Source", "Detector", "Angle", "Position", "Distance"]
    
    found_private = False
    for elem in ds:
        # Check if it's a private tag (odd group number)
        is_private = elem.tag.group % 2 != 0
        
        # Check keywords in name
        has_keyword = any(k.lower() in elem.name.lower() for k in keywords)
        
        if is_private or has_keyword:
            # Filter out some common non-geometry tags to reduce noise if needed, 
            # but for now let's print them to be sure.
            # Skip Pixel Data
            if elem.tag == (0x7fe0, 0x0010): 
                continue
                
            logger.info(f"{elem.tag} {elem.name}: {str(elem.value)[:100]}") # Truncate long values
            found_private = True

    if not found_private:
        logger.info("未找到明显的私有几何标签")
    
    logger.info(f"DICOM几何信息检查完成: {os.path.basename(file_path)}")

def main():
    logger.info("开始执行DICOM几何信息检查脚本")
    spine_dir = "spine"
    if not os.path.exists(spine_dir):
        logger.error(f"目录不存在: {spine_dir}")
        return

    files = [f for f in os.listdir(spine_dir) if f.lower().endswith(".dcm")]
    logger.info(f"在目录 '{spine_dir}' 中找到 {len(files)} 个DICOM文件")
    if not files:
        logger.warning(f"在目录 '{spine_dir}' 中未找到.dcm文件")
        return

    for f in files:
        file_path = os.path.join(spine_dir, f)
        logger.info(f"处理文件: {f}")
        check_dicom_geometry(file_path)
        logger.debug(f"完成文件检查: {f}")

if __name__ == "__main__":
    try:
        main()
        logger.info("DICOM几何信息检查脚本执行完成")
    except Exception as e:
        logger.error(f"脚本执行失败: {str(e)}", exc_info=True)
        sys.exit(1)
