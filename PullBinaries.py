import subprocess
import json
import glob
import os.path
import logging
import os
import psutil
import shutil
import xml.etree.ElementTree as ET
import _winapi
import multiprocessing
import sys

# Globals
binaries_folder_name = "Binaries"
config_name = "ProjectBorealisPackages.config"
uproject_path = "../ProjectBorealis.uproject"
uproject_version_key = "EngineAssociation"
read_only_api_key = "2ybrahtgwjb4lo6ww5h63u63wx3fkcx2rbvtnfwfdo44kyrwbyxa"
source_uri = "https://pkgs.dev.azure.com/Project-Borealis/_packaging/Binaries/nuget/v3/index.json"

already_installed_log = "is already installed"
successfully_installed_log = "Successfully installed"
package_not_installed_log = "is not found in the following primary"
source_already_added_log = "Please provide a unique name"
source_added_successfully_log = "added successfully"
##################################################

def HandleSources():
    try:
        output = subprocess.check_output(["nuget.exe", "sources", "Add", "-Name", binaries_folder_name, "-Source", source_uri], stderr=subprocess.STDOUT)
        subprocess.check_output(["nuget.exe", "setapikey", read_only_api_key, "-Source", binaries_folder_name])
    except subprocess.CalledProcessError as e:
        if source_already_added_log in str(e.output):
            print("Source address is valid: " + source_uri)
            return True
        else:
            print("Unknown error while trying to add " + source_uri + " with name of " + binaries_folder_name)
            print("Trace log:")
            print(e.output)
            return False

    if source_added_successfully_log in str(output):
        print("Source " + source_uri + " added successfully with name of " + binaries_folder_name)
        return True
    else:
        print("Unknown error while trying to add " + source_uri + " with name of " + binaries_folder_name)
        print("Trace log:")
        print(output)
        return False

def CleanOldVersions(package_id, package_version):
    # Find different versions than defined in config file
    other_versions = [name for name in os.listdir(".") if os.path.isdir(name) and name.split(".")[0] == package_id and name.split(package_id + ".")[1] != package_version]
    
    # Remove old versions
    for package_root in other_versions:
        try:
            shutil.rmtree(os.path.abspath(package_root))
        except:
            # We don't want to bloat user's package root with old packages
            # If removal was unsuccessful, prompt user to remove them manually before continuing installation
            print("Error while trying to clean deprecated package in " + os.path.abspath(package_root))
            print("Please remove that package manually, and run the nuget pull command again.")
            return False

    return True

def InstallPackage(package_id, package_version):
    try:
        output = subprocess.check_output(["nuget.exe", "install", package_id, "-Version", package_version, "-NonInteractive"])
    except subprocess.CalledProcessError as e:
        if package_not_installed_log in str(e.output):
            print(package_id + ": " + package_version + " installation failed.")
            return False
        elif successfully_installed_log in str(output):
            print(package_id + ": " + package_version + " is successfully installed!")
            return True
        else:
            print("Unknown error while installing " + package_id + ": " + package_version)
            print("Trace log:")
            print(e.output)
            return False
    
    if already_installed_log in str(output):
        print(package_id + ": " + package_version + " is already installed. Skipping the package...")
        return True
    elif successfully_installed_log in str(output):
        print(package_id + ": " + package_version + " is successfully installed!")
        return True
    else:
        print("Unknown error while installing " + package_id + ": " + package_version)
        print("Trace log:")
        print(output)
        return False

def GetSuffix():
    try:
        with open(uproject_path, "r") as uproject_file:  
            data = json.load(uproject_file)
            engine_association = data[uproject_version_key]
            return engine_association[-8:]
    except:
        print("Could not parse custom engine version from .uproject file")
        return ""
    
    print("Could not parse custom engine version from .uproject file")
    return ""

def CleanJunction(destination):
    # Remove existing junction first
    if os.path.islink(destination):
        os.unlink(destination)
    elif os.path.isdir(destination):
        try:
            # Only remove the junction point, do not touch actual package files
            os.remove(destination)
        except:
            pass

def CreateJunctionFromPackage(source, destination):
    if os.path.islink(destination):
        os.unlink(destination)
    elif os.path.isdir(destination):
        try:
            # Only remove the junction point, do not touch actual package files
            os.remove(destination)
        except:
            print("Folder is not empty. Clearing existing binaries in " + destination)
            # It's a real folder, purge it
            shutil.rmtree(destination)
    elif os.path.isfile(destination):
        # Somehow it's a file, remove it
        os.remove(destination)
          
    # Create junction from package contents to destination
    _winapi.CreateJunction(source, destination)

def ProcessPackage(package):
    try:
        package_id = package.attrib['id']
    except:
        print("Can't find id property for " + package + ". This package won't be installed.")
        return False
    
    try:
        package_version = package.attrib['version']
    except:
        print("Can't find version property for " + package_id + ". This package won't be installed.")
        return False

    version_suffix = GetSuffix() 

    # Could not get suffix version, return
    if version_suffix == "":
        return False

    package_version = package_version + "-" + version_suffix

    try:
        package_destination = os.path.join(package.attrib['destination'], binaries_folder_name)
    except:
        print("Can't find destination property for " + package_id + ". This package won't be installed.")
        return False
    
    full_name = package_id + "." + package_version

    result = CleanOldVersions(package_id, package_version)

    # Error while cleaning old packages, do not install new one until they're cleaned
    # TODO: Is that logically correct?
    if not result:
        return False

    result = InstallPackage(package_id, package_version)

    if result:
        CreateJunctionFromPackage(os.path.abspath(os.path.join(full_name, binaries_folder_name)), os.path.abspath(package_destination))
        return True
    else:
        print("Removing previously created junction links for " + package_id + "...")
        CleanJunction(os.path.abspath(package_destination))
        return False

def main():
    print("Starting pull command...")

    # Do not execute if Unreal Editor is running
    if "UE4Editor.exe" in (p.name() for p in psutil.process_iter()):
        print("Unreal Editor is running. Please close it before running pull command!")
        exit()

    # Register source & apply api key
    if not HandleSources():
        exit()

    # Parse packages xml file
    config_xml = ET.parse(config_name)
    packages = config_xml.getroot()

    pool = multiprocessing.Pool(multiprocessing.cpu_count())

    # Async process packages
    results = pool.map_async(ProcessPackage, [package for package in packages.findall("package")])

    # Release threads
    pool.close()
    pool.join()

if __name__ == '__main__':
     main()