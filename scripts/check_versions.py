import os
import requests
import re
import subprocess
import json

# --- Configuration for Patch Sources ---
SOURCES = {
    "revanced": {
        "patches_repo": "ReVanced/revanced-patches",
        "cli_repo": "ReVanced/revanced-cli",
        "patches_asset": ".rvp",
        "cli_asset": ".jar"
    },
    "inotia00": {
        "patches_repo": "inotia00/revanced-patches",
        "cli_repo": "inotia00/revanced-cli", 
        "patches_asset": ".rvp", # Inotia now uses .rvp
        "cli_asset": ".jar"
    },
    "anddea": {
        "patches_repo": "anddea/revanced-patches",
        "cli_repo": "inotia00/revanced-cli", # Anddea often uses Inotia's CLI or compatible
        "patches_asset": ".rvp",
        "cli_asset": ".jar"
    }
}

APPS_TO_CHECK = [
    "com.google.android.youtube",
    "com.google.android.apps.youtube.music",
    "com.reddit.frontpage",
    "com.twitter.android",
    "com.spotify.music"
]

HEADERS = {"User-Agent": "Mozilla/5.0"}

def download_asset(repo, extension, output_dir):
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    try:
        resp = requests.get(url, headers=HEADERS).json()
        for asset in resp['assets']:
            if asset['name'].endswith(extension) and "source" not in asset['name']:
                # For CLI, prefer 'all.jar' if available
                if extension == ".jar" and "all" not in asset['name'] and any("all" in a['name'] for a in resp['assets']):
                    continue
                
                download_url = asset['browser_download_url']
                filename = os.path.join(output_dir, asset['name'])
                if not os.path.exists(filename):
                    print(f"Downloading {asset['name']} from {repo}...")
                    with requests.get(download_url, stream=True) as r:
                        with open(filename, 'wb') as f:
                            for chunk in r.iter_content(chunk_size=8192):
                                f.write(chunk)
                return filename
    except Exception as e:
        print(f"Error fetching {repo}: {e}")
    return None

def check_versions():
    os.makedirs("tools_check", exist_ok=True)
    
    print(f"{'Source':<15} | {'App Package':<40} | {'Recommended Version'}")
    print("-" * 80)

    for source_name, config in SOURCES.items():
        # Download tools
        cli_path = download_asset(config["cli_repo"], config["cli_asset"], "tools_check")
        patches_path = download_asset(config["patches_repo"], config["patches_asset"], "tools_check")

        if not cli_path or not patches_path:
            print(f"{source_name:<15} | ERROR: Could not download tools")
            continue

        # Run List Patches
        try:
            cmd = ["java", "-jar", cli_path, "list-patches", "--with-packages", "--with-versions", patches_path]
            output = subprocess.check_output(cmd, text=True)
        except Exception as e:
            print(f"{source_name:<15} | CLI Error: {e}")
            continue

        # Parse versions
        for app in APPS_TO_CHECK:
            versions = set()
            # Regex to find package name followed by versions in parentheses
            # Handles "com.pkg (v1, v2)" format
            for line in output.splitlines():
                if app in line:
                    matches = re.findall(r'\(([\d\.,\s\w]+)\)', line)
                    for match in matches:
                        raw_vs = re.split(r'[,\s]+', match)
                        for v in raw_vs:
                            if re.match(r'^\d+(\.\d+)+$', v.strip()):
                                versions.add(v.strip())
            
            if versions:
                # Sort and pick latest
                sorted_vs = sorted(list(versions), key=lambda x: [int(i) for i in x.split('.') if i.isdigit()], reverse=True)
                print(f"{source_name:<15} | {app:<40} | {sorted_vs[0]}")
            else:
                print(f"{source_name:<15} | {app:<40} | Any/Universal")

if __name__ == "__main__":
    check_versions()
