import subprocess
import json
import glob
import os.path
import os
import xml.etree.ElementTree as ET

def RegisterSource(nuspec_name):
    with open(nuspec_name, "r") as nuspec_file:
        tree = ET.parse(nuspec_file)
        root = tree.getroot()
        source_uri = root.find('metadata/projectUrl').text

        # TODO: Ignore if source already exists
        subprocess.call(["nuget.exe", "sources", "Add", "-Name", "Binaries", "-Source", source_uri])

def PreparePackage(package_id, package_version):
    subprocess.call(["nuget.exe", "pack", "Nuspec/" + package_id + ".nuspec", "-Version", package_version, "-NoPackageAnalysis"])
    return package_id + "." + package_version + ".nupkg"

def PushPackage(package_full_name, source_name):
    subprocess.call(["nuget.exe", "push", "-Source", source_name, "-ApiKey", "AzureDevOps", package_full_name])

def GetSuffix():
    uproject_path = "../ProjectBorealis.uproject"
    uproject_version_key = "EngineAssociation"

    with open(uproject_path, "r") as uproject_file:  
        data = json.load(uproject_file)
        engine_association = data[uproject_version_key]
        return engine_association[-8:]
    # TODO: Error
    return "19800101"

def GetProjectVersion():
    defaultgame_path = "../Config/DefaultGame.ini"
    defaultgame_version_key = "ProjectVersion="

    with open(defaultgame_path, "r") as ini_file:
        for ln in ini_file:
            if ln.startswith(defaultgame_version_key):
                return ln.replace(defaultgame_version_key, '').rstrip()
    # TODO: Error
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

    print("Pushing binaries for " + package_id + ", Version: " + package_version + " ...")
    
    # Add engine version suffix
    package_version = package_version + "-" + GetSuffix()

    # Create nupkg file
    package_full_name = PreparePackage(package_id, package_version)

    # Push prepared package
    PushPackage(package_full_name, "Binaries")

    # Cleanup
    os.remove(package_full_name)

    print("Pushed binaries for " + package_id + ", Version: " + package_version + " !")
