#TODO: Create a py file for common variables & functions

import subprocess
import json
import glob
import os.path
import logging
import os
import psutil
import signal
import shutil
import xml.etree.ElementTree as ET
import _winapi
import multiprocessing

# Globals
binaries_folder_name = "Binaries"
uproject_path = "../ProjectBorealis.uproject"
uproject_version_key = "EngineAssociation"
read_only_api_key = "2ybrahtgwjb4lo6ww5h63u63wx3fkcx2rbvtnfwfdo44kyrwbyxa"
source_uri = "https://pkgs.dev.azure.com/Project-Borealis/_packaging/Binaries/nuget/v3/index.json"

source_already_added_log = "Please provide a unique name"
source_added_successfully_log = "added successfully"
##################################################

def InterruptHandler(signal, frame):
    # Cleanup
    print("Cleaning up temporary .nuget packages...")
    for nuspec_file in glob.glob("*.nupkg"):
        try:
            os.remove(nuspec_file)
            print("Removed: " + nuspec_file)
        except:
            print("Error while trying to remove temporary nupkg file: " + nuspec_file)
    exit()

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

def PreparePackage(package_id, package_version):
    # TODO: Error handling
    subprocess.call(["nuget.exe", "pack", "Nuspec/" + package_id + ".nuspec", "-Version", package_version, "-NoPackageAnalysis"])
    return package_id + "." + package_version + ".nupkg"

def PushPackage(package_full_name, source_name):
    # TODO: Error handling
    subprocess.call(["nuget.exe", "push", "-Source", source_name, "-ApiKey", "AzureDevOps", package_full_name])

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

def GetProjectVersion():
    defaultgame_path = "../Config/DefaultGame.ini"
    defaultgame_version_key = "ProjectVersion="

    with open(defaultgame_path, "r") as ini_file:
        for ln in ini_file:
            if ln.startswith(defaultgame_version_key):
                return ln.replace(defaultgame_version_key, '').rstrip()

    return "0.0.0"

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

def main():
    print("Starting push command...")

    signal.signal(signal.SIGINT, InterruptHandler)
    signal.signal(signal.SIGTERM, InterruptHandler)

    # Register source & apply api key
    if not HandleSources():
        exit()

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
        PushPackage(package_full_name, "Binaries")

        # Cleanup
        try:
            os.remove(package_full_name)
        except:
            print("Error while trying to remove temporary nupkg file: " + package_full_name)

        print("Successfully pushed binaries for " + package_id + ", Version: " + package_version + " !")

if __name__ == '__main__':
     main()