import subprocess
import json
import glob
import os.path
import logging
import os
import psutil
import shutil
import signal
import xml.etree.ElementTree as ET
import _winapi
import multiprocessing
import sys
import argparse

# Globals
pbget_version = "0.0.1"
binaries_folder_name = "Binaries"
nuget_source = "https://api.nuget.org/v3/index.json"
config_name = "PBGet.config"
uproject_path = "../ProjectBorealis.uproject"
uproject_version_key = "EngineAssociation"

push_timeout = 3600
already_installed_log = "is already installed"
successfully_installed_log = "Successfully installed"
package_not_installed_log = "is not found in the following primary"
##################################################

def PushInterruptHandler(signal, frame):
    # Cleanup
    print("Cleaning up temporary .nuget packages...")
    for nuspec_file in glob.glob("*.nupkg"):
        try:
            os.remove(nuspec_file)
            print("Removed: " + nuspec_file)
        except:
            print("Error while trying to remove temporary nupkg file: " + nuspec_file)
    sys.exit()

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

def GetPluginVersion(plugin_name):
    plugin_root = "../Plugins/" + plugin_name
    uplugin_version_key = "VersionName"

    for uplugin_path in glob.glob(plugin_root + "/*.uplugin"):
        with open(uplugin_path, "r") as uplugin_file:  
            data = json.load(uplugin_file)
            version = data[uplugin_version_key]

            # Some plugins have strange versions with only major and minor versions, add patch version for compatibility with nuget
            if version.count('.') == 1:
                version = version + ".0"
            
            return version

    return "0.0.0"

def GetProjectVersion():
    defaultgame_path = "../Config/DefaultGame.ini"
    defaultgame_version_key = "ProjectVersion="

    with open(defaultgame_path, "r") as ini_file:
        for ln in ini_file:
            if ln.startswith(defaultgame_version_key):
                return ln.replace(defaultgame_version_key, '').rstrip()

    return "0.0.0"

def GetSuffix():
    try:
        with open(uproject_path, "r") as uproject_file:  
            data = json.load(uproject_file)
            engine_association = data[uproject_version_key]
            return "b" + engine_association[-8:]
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

def PreparePackage(package_id, package_version):
    # TODO: Error handling
    subprocess.call(["nuget.exe", "pack", "Nuspec/" + package_id + ".nuspec", "-Version", package_version, "-NoPackageAnalysis"])
    return package_id + "." + package_version + ".nupkg"

def PushPackage(package_full_name, source_name):
    # TODO: Error handling
    subprocess.call(["nuget.exe", "push", "-Timeout", push_timeout, "-Source", source_name, package_full_name])

def CleanPackage(package):
    try:
        package_id = package.attrib['id']
    except:
        print("Can't find id property for " + package + ". This package won't be cleaned.")
        return False
    
    try:
        package_version = package.attrib['version']
    except:
        print("Can't find version property for " + package_id + ". This package won't be cleaned.")
        return False

    version_suffix = GetSuffix() 

    # Could not get suffix version, return
    if version_suffix == "":
        return False

    package_version = package_version + "-" + version_suffix

    try:
        package_destination = os.path.join(package.attrib['destination'], binaries_folder_name)
    except:
        print("Can't find destination property for " + package_id + ". This package won't be cleaned.")
        return False
    
    full_name = package_id + "." + package_version

    # Hack to remove all versions of this package
    CleanOldVersions(package_id, "")

    CleanJunction(os.path.abspath(package_destination))

    return True

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

def CommandClean():
    print("Initiating PBGet clean command...")

    # Do not execute if Unreal Editor is running
    if "UE4Editor.exe" in (p.name() for p in psutil.process_iter()):
        print("Unreal Editor is running. Please close it before running pull command!")
        sys.exit()

    # Parse packages xml file
    config_xml = ET.parse(config_name)
    packages = config_xml.getroot()

    pool = multiprocessing.Pool(multiprocessing.cpu_count())

    # Async process packages
    pool.map_async(CleanPackage, [package for package in packages.findall("package")])

    # Release threads
    pool.close()
    pool.join()

def CommandPull():
    print("Initiating PBGet pull command...")

    # Do not execute if Unreal Editor is running
    if "UE4Editor.exe" in (p.name() for p in psutil.process_iter()):
        print("Unreal Editor is running. Please close it before running pull command!")
        sys.exit()

    # Parse packages xml file
    config_xml = ET.parse(config_name)
    packages = config_xml.getroot()

    pool = multiprocessing.Pool(multiprocessing.cpu_count())

    # Async process packages
    pool.map_async(ProcessPackage, [package for package in packages.findall("package")])

    # Release threads
    pool.close()
    pool.join()

def CommandPush():
    print("Initiating PBGet push command...")

    signal.signal(signal.SIGINT, PushInterruptHandler)
    signal.signal(signal.SIGTERM, PushInterruptHandler)

    # Iterate each nuspec file
    for nuspec_file in glob.glob("Nuspec/*.nuspec"):
        # RegisterSource(nuspec_file)
        tree = ET.parse(nuspec_file)
        root = tree.getroot()

        package_id = root.find('metadata/id').text
        package_type = root.find('metadata/tags').text
        package_version = "0.0.0"

        if package_type == "Main":
            package_version = GetProjectVersion()
        elif package_type == "Plugin":
            package_version = GetPluginVersion(package_id)
        else:
            print("Unknown .nuspec package tag found for " + package_id + ". Skipping...")
            continue

        if(package_version == "0.0.0"):
            print("Could not get version for " + package_id + ". Skipping...")
            continue

        # Get engine version suffix
        suffix_version = GetSuffix()
        if suffix_version == "":
            continue

        package_version = package_version + "-" + suffix_version

        # Create nupkg file
        package_full_name = PreparePackage(package_id, package_version)

        # Push prepared package
        PushPackage(package_full_name, nuget_source)

        # Cleanup
        try:
            os.remove(package_full_name)
        except:
            print("Error while trying to remove temporary nupkg file: " + package_full_name)

        print("Successfully pushed binaries for " + package_id + ", Version: " + package_version + " !")

def main():
    parser = argparse.ArgumentParser(description='PBGet v' + pbget_version)

    FUNCTION_MAP = {'pull' : CommandPull, 'push' : CommandPush, 'clean' : CommandClean}

    parser.add_argument('command', choices=FUNCTION_MAP.keys())

    args = parser.parse_args()
    func = FUNCTION_MAP[args.command]
    func()

if __name__ == '__main__':
    multiprocessing.freeze_support()
    main()