import os
import requests
import re
import subprocess
import sys

# --- Configuration ---
APK_REPO_OWNER = "krishhari2105"
APK_REPO_NAME = "base-apks"
# Raw URL format: https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}
APK_BASE_URL = f"https://raw.githubusercontent.com/{APK_REPO_OWNER}/{APK_REPO_NAME}/main/apps"

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

# Mapping common names to package names for version checking
PKG_MAP = {
    "youtube": "com.google.android.youtube",
    "yt-music": "com.google.android.apps.youtube.music",
    "reddit": "com.reddit.frontpage",
    "twitter": "com.twitter.android",
    "spotify": "com.spotify.music"
}

def log(msg):
    print(f"[+] {msg}", flush=True)

def error(msg):
    print(f"[!] {msg}", flush=True)
    sys.exit(1)

def download_file(url, filename):
    log(f"Downloading {url} -> {filename}")
    headers = {"User-Agent": "Mozilla/5.0"}
    # If repo is private, we'd need: headers["Authorization"] = f"token {os.environ['GITHUB_TOKEN']}"
    
    with requests.get(url, stream=True, headers=headers) as r:
        if r.status_code == 404:
            return False
        r.raise_for_status()
        with open(filename, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
    return True

def fetch_tools(source_key):
    config = SOURCES.get(source_key)
    if not config: error(f"Invalid source: {source_key}")
    
    os.makedirs("tools", exist_ok=True)
    
    # Helper to get asset URL
    def get_asset_url(repo, ext):
        api_url = f"https://api.github.com/repos/{repo}/releases/latest"
        resp = requests.get(api_url).json()
        for asset in resp['assets']:
            if asset['name'].endswith(ext) and "source" not in asset['name']:
                 if ext == ".jar" and "all" not in asset['name'] and any("all" in a['name'] for a in resp['assets']):
                    continue
                 return asset['browser_download_url'], asset['name']
        return None, None

    # Download CLI
    cli_url, cli_name = get_asset_url(config['cli_repo'], config['cli_asset'])
    cli_path = f"tools/{cli_name}"
    download_file(cli_url, cli_path)
    
    # Download Patches
    patches_url, patches_name = get_asset_url(config['patches_repo'], config['patches_asset'])
    patches_path = f"tools/{patches_name}"
    download_file(patches_url, patches_path)
    
    return cli_path, patches_path

def get_target_version(cli_path, patches_path, package_name, manual_version):
    if manual_version and manual_version != "auto":
        log(f"Manual version override: {manual_version}")
        return manual_version
        
    log(f"Auto-detecting version for {package_name}...")
    cmd = ["java", "-jar", cli_path, "list-patches", "--with-packages", "--with-versions", patches_path]
    try:
        output = subprocess.check_output(cmd, text=True)
        versions = set()
        for line in output.splitlines():
            if package_name in line:
                matches = re.findall(r'\(([\d\.,\s\w]+)\)', line)
                for match in matches:
                    raw_vs = re.split(r'[,\s]+', match)
                    for v in raw_vs:
                        if re.match(r'^\d+(\.\d+)+$', v.strip()):
                            versions.add(v.strip())
        
        if versions:
            sorted_vs = sorted(list(versions), key=lambda x: [int(i) for i in x.split('.') if i.isdigit()], reverse=True)
            log(f"Detected latest compatible version: {sorted_vs[0]}")
            return sorted_vs[0]
            
    except Exception as e:
        log(f"Error detecting version: {e}")
        
    error("Could not determine version automatically. Please verify patches or use manual override.")

def main():
    app_name = os.environ.get("APP_NAME") # e.g., "youtube"
    patch_source = os.environ.get("PATCH_SOURCE") # e.g., "revanced"
    manual_version = os.environ.get("VERSION", "auto")
    
    if not app_name or not patch_source:
        error("Missing required env vars")

    # 1. Fetch Tools
    cli_path, patches_path = fetch_tools(patch_source)
    
    # 2. Determine Version
    package_name = PKG_MAP.get(app_name, "")
    target_version = get_target_version(cli_path, patches_path, package_name, manual_version)
    
    # 3. Download APK from Repo
    # Construct URL: youtube-v19.16.39.apk
    # Note: Ensure your repo filenames match this pattern strictly!
    apk_filename = f"{app_name}-v{target_version}.apk"
    download_url = f"{APK_BASE_URL}/{apk_filename}"
    
    os.makedirs("downloads", exist_ok=True)
    local_apk_path = f"downloads/{apk_filename}"
    
    log(f"Attempting download from: {download_url}")
    success = download_file(download_url, local_apk_path)
    
    if not success:
        error(f"Failed to download APK from repo. Verify file exists: {apk_filename}")
        
    # 4. Patch
    output_apk = f"build/{app_name}-{patch_source}-v{target_version}.apk"
    os.makedirs("build", exist_ok=True)
    
    cmd = [
        "java", "-jar", cli_path,
        "patch",
        "-p", patches_path,
        "-o", output_apk,
        local_apk_path
    ]
    
    log("Running patcher...")
    try:
        subprocess.run(cmd, check=True)
        log(f"Build Success: {output_apk}")
        with open(os.environ['GITHUB_ENV'], 'a') as f:
            f.write(f"PATCHED_APK={output_apk}\n")
            f.write(f"APP_VERSION={target_version}\n")
    except subprocess.CalledProcessError:
        error("Patching failed")

if __name__ == "__main__":
    main()
