import subprocess
import glob
import os.path
import os
import signal
import xml.etree.ElementTree as ET
import _winapi
import sys
import argparse

# PBGet Imports
import PBVersion
import PBTools

# Multiprocessing
from multiprocessing.pool import ThreadPool
from multiprocessing import Manager
from multiprocessing import Value
from multiprocessing import cpu_count
from multiprocessing import freeze_support

# Colored Output
import colorama
from colorama import Fore, Back, Style


### Globals
pbget_version = "0.0.3"

binaries_folder_name = "Binaries"
nuget_source = "https://api.nuget.org/v3/index.json"
config_name = "PBGet.packages"

push_package_input = ""

package_ext = ".nupkg"
metadata_ext = ".nuspec"

push_timeout = 3600
error_state = Value('i', 0)
warning_state = Value('i', 0)

already_installed_log = "is already installed"
successfully_installed_log = "Successfully installed"
package_not_installed_log = "is not found in the following primary"
############################################################################

### LOGGER
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
############################################################################

### Subprocess commands
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

def PreparePackage(package_id, package_version):
    return subprocess.call(["nuget.exe", "pack", "Nuspec/" + package_id + metadata_ext, "-Version", package_version, "-NoPackageAnalysis"])

def PushPackage(package_full_name, source_name):
    return subprocess.call(["nuget.exe", "push", "-Timeout", str(push_timeout), "-Source", source_name, package_full_name])
############################################################################

### Other Functions
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

def IgnoreExistingInstallations(packages):
    fmt = '{:<25} {:<25} {:<40}'
    for package in packages.findall("package"):
        package_id = package.attrib['id']
        package_version = package.attrib['version'] + "-" + PBVersion.GetSuffix()
        if PBTools.CheckInstallation(package_id, package_version):
            LogSuccess(fmt.format(package_id, package_version, "Version already installed"), False)
            packages.remove(package)
    return packages

def CreateJunctionFromPackage(source, destination):
    # Before creating a junction, clean the destionation path first
    if not PBTools.PurgeDestionation(destination):
        LogError("Can't clean existing files in destionation junction point: " + destination)
       
    # Create junction from package contents to destination
    try:
        _winapi.CreateJunction(source, destination)
    except:
        LogError("Can't create junction point from " + source + " to " + destination)

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

    PBTools.CleanPreviousInstallations(package_id)

    abs_destionation = os.path.abspath(package_destination)
    if not PBTools.PurgeDestionation(abs_destionation):
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

    version_suffix = PBVersion.GetSuffix() 

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
    
    PBTools.CleanPreviousInstallations(package_id)

    full_name = package_id + "." + package_version
    if InstallPackage(package_id, package_version):
        CreateJunctionFromPackage(os.path.abspath(os.path.join(full_name, binaries_folder_name)), os.path.abspath(package_destination))
    else:
        # Try removing faulty junction
        PBTools.RemoveFaultyJunction(os.path.abspath(package_destination))

def PushFromNuspec(nuspec_file):
    tree = ET.parse(nuspec_file)
    root = tree.getroot()

    package_id = root.find('metadata/id').text
    package_type = root.find('metadata/tags').text
    package_version = "0.0.0"

    if package_type == "Main":
        package_version = PBVersion.GetProjectVersion()
    elif package_type == "Plugin":
        package_version = PBVersion.GetPluginVersion(package_id)
    else:
        LogWarning("Unknown .nuspec package tag found for " + package_id + ". Skipping...")
        return False

    if(package_version == "0.0.0"):
        LogWarning("Could not get version for " + package_id + ". Skipping...")
        return False

    # Get engine version suffix
    suffix_version = PBVersion.GetSuffix()
    if suffix_version == "":
        LogError("Could not parse custom engine version from .uproject file.")
        return False

    package_version = package_version + "-" + suffix_version
    package_full_name = package_id + "." + package_version + package_ext

    # Create nupkg file
    PreparePackage(package_id, package_version)

    # Push prepared package
    if PushPackage(package_full_name, nuget_source) != 0:
        LogError("Could not push package into source: " + package_full_name)
        return False

    # Cleanup
    try:
        os.remove(package_full_name)
    except:
        LogWarning("Cannot remove temporary nupkg file: " + package_full_name)

    LogSuccess("Push successful: " + package_id + "." + package_version)
    return True
############################################################################

### Argparser Command Functions
def CommandResetCache():
    LogSuccess("\nInitiating PBGet reset cache command...", False)
    print("\n*************************\n")
    return subprocess.call(["nuget.exe", "locals", "all", "-list"])

def CommandClean():
    LogSuccess("\nInitiating PBGet clean command...", False)
    print("\n*************************\n")

    # Do not execute if Unreal Editor is running
    if PBTools.CheckRunningProcess("UE4Editor.exe"):
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
    if PBTools.CheckRunningProcess("UE4Editor.exe"):
        LogError("Unreal Editor is running. Please close it before running pull command")
        sys.exit(1)

    # Parse packages xml file
    config_xml = ET.parse(config_name)

    fmt = '{:<28} {:<37} {:<10}'
    print(fmt.format("  ~Package Name~", "~Version~", "~Result~"))
    packages = IgnoreExistingInstallations(config_xml.getroot())
    
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

    if push_package_input == "":
        # No package name provided by user
        LogSuccess("All packages will be pushed...", False)
        # Iterate each nuspec file
        for nuspec_file in glob.glob("Nuspec/*.nuspec"):
            PushFromNuspec(nuspec_file)
    else:
        LogSuccess("Only " + push_package_input + " will be pushed...", False)
        PushFromNuspec("Nuspec/" + push_package_input + ".nuspec")
############################################################################

def main():
    parser = argparse.ArgumentParser(description='PBGet v' + pbget_version)

    FUNCTION_MAP = {'pull' : CommandPull, 'push' : CommandPush, 'clean' : CommandClean, 'resetcache' : CommandResetCache}

    parser.add_argument('command', choices=FUNCTION_MAP.keys())
    parser.add_argument("--package")

    args = parser.parse_args()

    global push_package_input
    if PBTools.CheckInputPackage(args.package):
        push_package_input = args.package
        push_package_input.replace(".nuspec", "")

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