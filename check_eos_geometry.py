import pydicom
import os
import sys

def check_dicom_geometry(file_path):
    print(f"--- Inspecting: {os.path.basename(file_path)} ---")
    try:
        ds = pydicom.dcmread(file_path)
    except Exception as e:
        print(f"Error reading file: {e}")
        return

    # 1. Check Standard Geometry Tags
    print("\n[Standard Geometry Tags]")
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
            print(f"{elem.name} ({elem.tag}): {elem.value}")
            found_standard = True
    
    if not found_standard:
        print("No standard geometry tags found.")

    # 2. Search for Private Tags or Keywords
    print("\n[Potential EOS/Geometry Private Tags & Keywords]")
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
                
            print(f"{elem.tag} {elem.name}: {str(elem.value)[:100]}") # Truncate long values
            found_private = True

    if not found_private:
        print("No obvious private geometry tags found.")

def main():
    print("Starting script...")
    spine_dir = "spine"
    if not os.path.exists(spine_dir):
        print(f"Directory '{spine_dir}' not found.")
        return

    files = [f for f in os.listdir(spine_dir) if f.lower().endswith(".dcm")]
    print(f"Found {len(files)} DICOM files.")
    if not files:
        print(f"No .dcm files found in '{spine_dir}'.")
        return

    for f in files:
        check_dicom_geometry(os.path.join(spine_dir, f))
        print("\n" + "="*50 + "\n")

if __name__ == "__main__":
    main()
