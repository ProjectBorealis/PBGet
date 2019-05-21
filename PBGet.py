import subprocess
import json
import glob
import os.path
import os
import psutil
import shutil
import signal
import xml.etree.ElementTree as ET
import _winapi
import sys
import argparse

from multiprocessing.pool import ThreadPool
from multiprocessing import Manager
from multiprocessing import Value
from multiprocessing import cpu_count
from multiprocessing import freeze_support

import colorama
from colorama import Fore, Back, Style

# Globals
pbget_version = "0.0.3"

binaries_folder_name = "Binaries"
nuget_source = "https://api.nuget.org/v3/index.json"
config_name = "PBGet.config"
uproject_path = "../ProjectBorealis.uproject"
uproject_version_key = "EngineAssociation"

package_ext = ".nupkg"
metadata_ext = ".nuspec"

push_timeout = 3600
error_state = Value('i', 0)
warning_state = Value('i', 0)

already_installed_log = "is already installed"
successfully_installed_log = "Successfully installed"
package_not_installed_log = "is not found in the following primary"
##################################################

def LogSuccess(message, prefix = True):
    global warning_state
    if prefix:
        print(Fore.GREEN + "SUCCESS: " + message + Style.RESET_ALL)
    else:
        print(Fore.GREEN + message + Style.RESET_ALL)

def LogWarning(message, prefix = True):
    global warning_state
    warning_state = Manager().Value('i', 1)
    if prefix:
        print(Fore.YELLOW + "WARNING: " + message + Style.RESET_ALL)
    else:
        print(Fore.YELLOW + message + Style.RESET_ALL)

def LogError(message, prefix = True):
    global error_state
    error_state = Manager().Value('i', 1)
    if prefix:
        print(Fore.RED +  "ERROR: " + message + Style.RESET_ALL)
    else:
        print(Fore.RED + message + Style.RESET_ALL)

def PushInterruptHandler(signal, frame):
    # Cleanup
    print("Cleaning up temporary .nuget packages...")
    for nuspec_file in glob.glob("*.nupkg"):
        try:
            os.remove(nuspec_file)
            print("Removed: " + nuspec_file)
        except:
            print(Fore.RED + "Error while trying to remove temporary nupkg file: " + nuspec_file + Style.RESET_ALL)
            sys.exit(1)
    sys.exit(0)

def CleanPreviousInstallations(package_id):
    # Find different versions than defined in config file
    other_versions = [name for name in os.listdir(".") if os.path.isdir(name) and name.split(".")[0] == package_id]
    
    for package_root in other_versions:
        try:
            shutil.rmtree(os.path.abspath(package_root))
        except:
            # Removal was unsuccessful
            print("Cannot clean deprecated package in " + os.path.abspath(package_root))

def InstallPackage(package_id, package_version):
    output = subprocess.getoutput(["nuget.exe", "install", package_id, "-Version", package_version, "-NonInteractive"])

    fmt = '{:<25} {:<25} {:<40}'
    if already_installed_log in str(output):
        LogSuccess(fmt.format(package_id, package_version, "Version already installed"), False)
        return True
    elif package_not_installed_log in str(output):
        LogError(fmt.format(package_id, package_version, "Not found in the repository"), False)
        return False
    elif successfully_installed_log in str(output):
        LogSuccess(fmt.format(package_id, package_version, "Installation successful")+ Style.RESET_ALL, False)
        return True
    else:
        LogError("Unknown error while installing " + package_id + ": " + package_version, False)
        LogError("Trace log:", False)
        LogError(output, False)
        return False

    print()

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
            build_version = "b" + engine_association[-8:]

            # We're using local build version in .uproject file
            if "}" in build_version:
                return ""

            return "b" + engine_association[-8:]
    except:
        return ""
    
    return ""

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
        try:
            shutil.rmtree(destination)
        except:
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

def CreateJunctionFromPackage(source, destination):
    # Before creating a junction, clean the destionation path first
    if not PurgeDestionation(destination):
        LogError("Can't clean existing files in destionation junction point: " + destination)
       
    # Create junction from package contents to destination
    try:
        _winapi.CreateJunction(source, destination)
    except:
        LogError("Can't create junction point from " + source + " to " + destination)

def PreparePackage(package_id, package_version):
    return subprocess.call(["nuget.exe", "pack", "Nuspec/" + package_id + ".nuspec", "-Version", package_version, "-NoPackageAnalysis"])

def PushPackage(package_full_name, source_name):
    return subprocess.call(["nuget.exe", "push", "-Timeout", str(push_timeout), "-Source", source_name, package_full_name])

def CleanPackage(package):
    try:
        package_id = package.attrib['id']
    except:
        LogError("Can't find id property for " + package + ". This package won't be cleaned.")
        return
    
    try:
        package_destination = os.path.join(package.attrib['destination'], binaries_folder_name)
    except:
        LogError("Can't find destination property for " + package_id + ". This package won't be cleaned.")
        return

    # Hack to remove all versions of this package
    CleanPreviousInstallations(package_id)

    abs_destionation = os.path.abspath(package_destination)
    if not PurgeDestionation(abs_destionation):
        LogError("Can't clean existing files in destionation junction point: " + abs_destionation)
        return

def ProcessPackage(package):
    try:
        package_id = package.attrib['id']
    except:
        LogError("Can't find id property for " + package + ". This package won't be installed.")
        return
   
    try:
        package_version = package.attrib['version']
    except:
        LogError("Can't find version property for " + package_id + ". This package won't be installed.")
        return

    version_suffix = GetSuffix() 

    # Could not get suffix version, return
    if version_suffix == "":
        LogError("Can't get version suffix for " + package_id + ". This package won't be cleaned.")
        return

    package_version = package_version + "-" + version_suffix

    try:
        package_destination = os.path.join(package.attrib['destination'], binaries_folder_name)
    except:
        LogError("Can't find destination property for " + package_id + ". This package won't be installed.")
        return
    
    CleanPreviousInstallations(package_id)

    full_name = package_id + "." + package_version
    if InstallPackage(package_id, package_version):
        CreateJunctionFromPackage(os.path.abspath(os.path.join(full_name, binaries_folder_name)), os.path.abspath(package_destination))
    else:
        # Try removing faulty junction
        RemoveFaultyJunction(os.path.abspath(package_destination))

def CommandResetCache():
    LogSuccess("\nInitiating PBGet reset cache command...", False)
    print("\n*************************\n")
    return subprocess.call(["nuget.exe", "locals", "all", "-list"])

def CommandClean():
    LogSuccess("\nInitiating PBGet clean command...", False)
    print("\n*************************\n")

    # Do not execute if Unreal Editor is running
    if "UE4Editor.exe" in (p.name() for p in psutil.process_iter()):
        LogError("Unreal Editor is running. Please close it before running pull command")
        sys.exit(1)

    # Parse packages xml file
    config_xml = ET.parse(config_name)
    packages = config_xml.getroot()
    
    pool = ThreadPool(cpu_count())

    # Async process packages
    pool.map_async(CleanPackage, [package for package in packages.findall("package")])

    # Release threads
    pool.close()
    pool.join()

def CommandPull():
    LogSuccess("\nInitiating PBGet pull command...", False)
    print("\n*************************\n")

    # Do not execute if Unreal Editor is running
    if "UE4Editor.exe" in (p.name() for p in psutil.process_iter()):
        LogError("Unreal Editor is running. Please close it before running pull command")
        sys.exit(1)

    # Parse packages xml file
    config_xml = ET.parse(config_name)
    packages = config_xml.getroot()

    fmt = '{:<28} {:<37} {:<10}'
    print(fmt.format("  ~Package Name~", "~Version~", "~Result~"))

    fmt = '{:<25} {:<25} {:<40}'
    for package in packages.findall("package"):
        package_id = package.attrib['id']
        package_version = package.attrib['version'] + "-" + GetSuffix()
        if CheckInstallation(package_id, package_version):
            LogSuccess(fmt.format(package_id, package_version, "Version already installed"), False)
            packages.remove(package)

    # Async process packages
    pool = ThreadPool(cpu_count())
    pool.map_async(ProcessPackage, [package for package in packages.findall("package")])

    # Release threads
    pool.close()
    pool.join()

def CommandPush():
    LogSuccess("\nInitiating PBGet push command...", False)
    print("\n*************************\n")

    signal.signal(signal.SIGINT, PushInterruptHandler)
    signal.signal(signal.SIGTERM, PushInterruptHandler)

    # Iterate each nuspec file
    for nuspec_file in glob.glob("Nuspec/*.nuspec"):
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
            print(Fore.YELLOW + "Unknown .nuspec package tag found for " + package_id + ". Skipping..." + Style.RESET_ALL)
            continue

        if(package_version == "0.0.0"):
            print(Fore.YELLOW + "Could not get version for " + package_id + ". Skipping..." + Style.RESET_ALL)
            continue

        # Get engine version suffix
        suffix_version = GetSuffix()
        if suffix_version == "":
            LogError("Could not parse custom engine version from .uproject file.")
            break

        package_version = package_version + "-" + suffix_version
        package_full_name = package_id + "." + package_version + package_ext

        # Create nupkg file
        PreparePackage(package_id, package_version)

        # Push prepared package
        PushPackage(package_full_name, nuget_source)

        # Cleanup
        try:
            os.remove(package_full_name)
        except:
            print(Fore.YELLOW +  "Cannot remove temporary nupkg file: " + package_full_name)

        LogSuccess("Push successful: " + package_id + "." + package_version)

def main():
    parser = argparse.ArgumentParser(description='PBGet v' + pbget_version)

    FUNCTION_MAP = {'pull' : CommandPull, 'push' : CommandPush, 'clean' : CommandClean, 'resetcache' : CommandResetCache}

    parser.add_argument('command', choices=FUNCTION_MAP.keys())

    args = parser.parse_args()
    func = FUNCTION_MAP[args.command]
    func()
    
    print("\n*************************\n")
    if error_state.value == 1:
        LogError("PBGet " + args.command + " operation completed with errors\n")
    elif warning_state.value == 1:
        LogWarning("PBGet " + args.command + " operation completed with warnings\n")
    else:
        LogSuccess("PBGet " + args.command + " operation completed without errors\n")
    sys.exit(error_state.value)

if __name__ == '__main__':
    freeze_support()
    colorama.init()
    main()