import os
import requests
import re
import subprocess
import json
import sys

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
        "patches_asset": ".rvp",
        "cli_asset": ".jar"
    },
    "anddea": {
        "patches_repo": "anddea/revanced-patches",
        "cli_repo": "inotia00/revanced-cli", 
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
        if 'assets' not in resp:
            print(f"Error: No assets found for {repo}")
            return None
            
        for asset in resp['assets']:
            if asset['name'].endswith(extension) and "source" not in asset['name']:
                if extension == ".jar" and "all" not in asset['name'] and any("all" in a['name'] for a in resp['assets']):
                    continue
                
                download_url = asset['browser_download_url']
                filename = os.path.join(output_dir, asset['name'])
                if not os.path.exists(filename):
                    print(f"Downloading {asset['name']} from {repo}...")
                    with requests.get(download_url, stream=True) as r:
                        r.raise_for_status()
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
        cli_path = download_asset(config["cli_repo"], config["cli_asset"], "tools_check")
        patches_path = download_asset(config["patches_repo"], config["patches_asset"], "tools_check")

        if not cli_path or not patches_path:
            print(f"{source_name:<15} | ERROR: Could not download tools")
            continue

        try:
            # Command changed to 'list-versions' as requested
            cmd = ["java", "-jar", cli_path, "list-versions", "-f", patches_path] 
            # -f flag sometimes needed for formatting, or just patches.rvp
            # We'll try bare command first: list-versions patches.rvp
            cmd = ["java", "-jar", cli_path, "list-versions", patches_path]
            
            output = subprocess.check_output(cmd, text=True)
        except Exception as e:
            # Fallback if list-versions fails (older CLIs might not have it)
            try:
                cmd = ["java", "-jar", cli_path, "list-patches", "--with-versions", patches_path]
                output = subprocess.check_output(cmd, text=True)
            except Exception as e2:
                print(f"{source_name:<15} | CLI Error: {e2}")
                continue

        # --- Parsing Logic ---
        # We need to map Package -> Versions
        # The output format often groups versions under packages.
        
        found_versions = {app: set() for app in APPS_TO_CHECK}
        current_package = None

        for line in output.splitlines():
            line = line.strip()
            if not line: continue

            # check if this line is a package name we care about
            is_package_line = False
            for app in APPS_TO_CHECK:
                if app in line:
                    current_package = app
                    is_package_line = True
                    break
            
            if is_package_line:
                continue

            # If we are under a package, look for versions
            if current_package:
                # Regex for version: 19.16.39 or v19.16.39
                # We strip common non-version chars
                v_match = re.search(r'\b(\d+\.\d+\.\d+)\b', line)
                if v_match:
                    found_versions[current_package].add(v_match.group(1))
                
                # Stop if we hit a line that looks like a different package or header (heuristic)
                # But 'list-versions' usually strictly lists them. 

        # Print Results
        for app in APPS_TO_CHECK:
            versions = found_versions[app]
            if versions:
                # Sort versions
                def version_sort_key(v):
                    try:
                        return [int(part) for part in v.split('.')]
                    except:
                        return [0]
                
                sorted_vs = sorted(list(versions), key=version_sort_key, reverse=True)
                print(f"{source_name:<15} | {app:<40} | {sorted_vs[0]}")
            else:
                print(f"{source_name:<15} | {app:<40} | Any/Universal")

if __name__ == "__main__":
    check_versions()
