import xml.etree.ElementTree as ET
import os.path
import os
import psutil
import shutil

def CheckRunningProcess(process_name):
    if process_name in (p.name() for p in psutil.process_iter()):
        return True
    return False

def CleanPreviousInstallations(package_id):
    # Find different versions than defined in config file
    other_versions = [name for name in os.listdir(".") if os.path.isdir(name) and name.split(".")[0] == package_id]
    
    for package_root in other_versions:
        try:
            shutil.rmtree(os.path.abspath(package_root))
        except:
            # Removal was unsuccessful
            print("Cannot clean deprecated package in " + os.path.abspath(package_root))

def CheckInstallation(package_id, package_version):
    # Check installation correctness from file list in related .nuspec file
    tree = ET.parse("Nuspec/" + package_id + ".nuspec")
    files = tree.findall('files/file')
    for file_entry in files:
        file_path = file_entry.attrib['src']
        file_path = file_path[file_path.index('/') + 1:]
        if not os.path.isfile(os.path.abspath(file_path)):
            return False
    
    if not os.path.isdir(os.path.abspath(package_id + "." + package_version)):
        return False
    
    # Package installation seems good
    return True
        
def RemoveFaultyJunction(destination):
    if os.path.isdir(destination):
        try:
            shutil.rmtree(destination)
        except:
            try:
                os.remove(destination)
            except:
                return False

def PurgeDestionation(destination):
    if os.path.islink(destination):
        try:
            os.unlink(destination)
        except:
            return False

    elif os.path.isdir(destination):
        is_junction = False

        try:
            shutil.rmtree(destination)
        except:
            is_junction = True

        if is_junction:
            try:
                os.remove(destination)
            except:
                return False
            

    elif os.path.isfile(destination):
        # Somehow it's a file, remove it
        try:
            os.remove(destination)
        except:
            return False

    return True