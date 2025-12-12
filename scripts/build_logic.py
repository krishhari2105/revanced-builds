import os
import requests
import re
import subprocess
import sys
import zipfile
import shutil

# --- Configuration ---
APK_REPO_OWNER = "krishhari2105"
APK_REPO_NAME = "base-apks"
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
    try:
        with requests.get(url, stream=True) as r:
            if r.status_code == 404: return False
            r.raise_for_status()
            with open(filename, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        return True
    except Exception as e:
        log(f"Download failed: {e}")
        return False

def fetch_tools(source_key):
    config = SOURCES.get(source_key)
    os.makedirs("tools", exist_ok=True)
    
    def get_asset(repo, ext):
        url = f"https://api.github.com/repos/{repo}/releases/latest"
        resp = requests.get(url).json()
        for asset in resp['assets']:
            if asset['name'].endswith(ext) and "source" not in asset['name']:
                if ext == ".jar" and "all" not in asset['name'] and any("all" in a['name'] for a in resp['assets']):
                    continue
                return asset['browser_download_url'], asset['name']
        return None, None

    cli_url, cli_name = get_asset(config['cli_repo'], config['cli_asset'])
    cli_path = f"tools/{cli_name}"
    if not os.path.exists(cli_path): download_file(cli_url, cli_path)
    
    patches_url, patches_name = get_asset(config['patches_repo'], config['patches_asset'])
    patches_path = f"tools/{patches_name}"
    if not os.path.exists(patches_path): download_file(patches_url, patches_path)
    
    return cli_path, patches_path

def fetch_apkeditor():
    """Downloads APKEditor for merging split APKs."""
    os.makedirs("tools", exist_ok=True)
    apkeditor_path = "tools/APKEditor.jar"
    if not os.path.exists(apkeditor_path):
        # Using a known reliable release of APKEditor (v1.4.0 is stable for merging)
        url = "https://github.com/REAndroid/APKEditor/releases/download/V1.4.0/APKEditor-1.4.0.jar"
        if not download_file(url, apkeditor_path):
             error("Failed to download APKEditor.jar")
    return apkeditor_path

def get_target_version(cli_path, patches_path, package_name, manual_version):
    if manual_version and manual_version != "auto":
        log(f"Manual version override: {manual_version}")
        return manual_version
        
    log(f"Auto-detecting version for {package_name}...")
    cmd = ["java", "-jar", cli_path, "list-versions", patches_path]
    try:
        output = subprocess.check_output(cmd, text=True)
        versions = []
        current_pkg = None
        
        for line in output.splitlines():
            line = line.strip()
            if not line: continue
            
            # Robust Package Header Match
            pkg_match = re.search(r"Package name:\s*([a-zA-Z0-9_.]+)", line)
            if pkg_match:
                current_pkg = pkg_match.group(1)
                continue
                
            if current_pkg == package_name:
                 # Version match
                 v_match = re.match(r'^(v?\d+(\.\d+)+)', line)
                 if v_match:
                     versions.append(v_match.group(1))

        if versions:
            # Sort desc
            versions.sort(key=lambda s: [int(x) for x in s.lstrip('v').split('.') if x.isdigit()], reverse=True)
            log(f"Detected latest compatible version: {versions[0]}")
            return versions[0]
            
    except Exception as e:
        log(f"Error detecting version: {e}")
        
    error("Could not determine version automatically.")

def merge_bundle(bundle_path, apkeditor_path):
    """
    Extracts a bundle (zip/apkm/apks) and merges it into a single APK.
    """
    log(f"Processing bundle: {bundle_path}")
    extract_dir = "extracted_bundle"
    if os.path.exists(extract_dir):
        shutil.rmtree(extract_dir)
    os.makedirs(extract_dir)
    
    # 1. Extract
    try:
        with zipfile.ZipFile(bundle_path, 'r') as z:
            z.extractall(extract_dir)
    except zipfile.BadZipFile:
        error("Downloaded file is not a valid zip/apkm file.")

    # 2. Merge
    output_merged = bundle_path.replace(".apkm", ".apk").replace(".apks", ".apk").replace(".xapk", ".apk")
    if output_merged == bundle_path:
        output_merged = bundle_path + "_merged.apk"

    log(f"Merging splits into: {output_merged}")
    
    # Command: java -jar APKEditor.jar m -i <dir> -o <out.apk>
    cmd = [
        "java", "-jar", apkeditor_path,
        "m", "-i", extract_dir, "-o", output_merged
    ]
    
    try:
        subprocess.run(cmd, check=True)
        log("Merge successful.")
        return output_merged
    except subprocess.CalledProcessError as e:
        error(f"Failed to merge APK bundle: {e}")

def main():
    app_name = os.environ.get("APP_NAME")
    patch_source = os.environ.get("PATCH_SOURCE")
    manual_version = os.environ.get("VERSION", "auto")
    
    if not app_name or not patch_source: error("Missing env vars")

    # 1. Tools
    cli_path, patches_path = fetch_tools(patch_source)
    
    # 2. Version
    pkg = PKG_MAP.get(app_name)
    version = get_target_version(cli_path, patches_path, pkg, manual_version)
    
    # 3. Download APK or Bundle
    # We try extensions in order: .apk -> .apkm -> .apks -> .xapk
    extensions = [".apk", ".apkm", ".apks", ".xapk"]
    downloaded_path = None
    
    os.makedirs("downloads", exist_ok=True)
    
    for ext in extensions:
        apk_file = f"{app_name}-v{version}{ext}"
        dl_url = f"{APK_BASE_URL}/{apk_file}"
        local_path = f"downloads/{apk_file}"
        
        log(f"Checking for {ext} file: {dl_url}")
        if download_file(dl_url, local_path):
            downloaded_path = local_path
            break
            
    if not downloaded_path:
        error(f"Could not download APK/Bundle for {app_name} v{version}. Checked extensions: {extensions}")

    # 4. Handle Bundle if needed
    final_apk_path = downloaded_path
    if downloaded_path.endswith((".apkm", ".apks", ".xapk")):
        apkeditor_path = fetch_apkeditor()
        final_apk_path = merge_bundle(downloaded_path, apkeditor_path)

    # 5. Patch
    out_apk = f"build/{app_name}-{patch_source}-v{version}.apk"
    os.makedirs("build", exist_ok=True)
    
    cmd = [
        "java", "-jar", cli_path,
        "patch",
        "-p", patches_path,
        "-o", out_apk,
        final_apk_path
    ]
    
    log("Running patcher...")
    try:
        subprocess.run(cmd, check=True)
        log(f"Success: {out_apk}")
        with open(os.environ['GITHUB_ENV'], 'a') as f:
            f.write(f"PATCHED_APK={out_apk}\n")
            f.write(f"APP_VERSION={version}\n")
    except:
        error("Patching failed")

if __name__ == "__main__":
    main()
