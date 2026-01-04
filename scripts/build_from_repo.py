import os
import requests
import re
import subprocess
import sys
import zipfile
import shutil
from datetime import datetime

# --- Configuration ---
APK_REPO_OWNER = "krishhari2105"
APK_REPO_NAME = "base-apks"

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
    },
    "morphe": {
        "patches_repo": "MorpheApp/morphe-patches",
        "cli_repo": "MorpheApp/morphe-cli",
        "patches_asset": ".mpp",
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
    raise Exception(msg)

def get_auth_headers():
    token = os.environ.get("PRIVATE_REPO_TOKEN")
    if token:
        return {"Authorization": f"token {token}", "User-Agent": "Mozilla/5.0"}
    return {"User-Agent": "Mozilla/5.0"}

def download_file(url, filename):
    log(f"Downloading {url} -> {filename}")
    try:
        headers = get_auth_headers()
        headers["Accept"] = "application/octet-stream"
        
        with requests.get(url, headers=headers, stream=True, allow_redirects=False) as r:
            if r.status_code == 404: 
                log(f"Error: 404 Not Found for {url}")
                return False
            
            final_url = url
            if r.status_code in (301, 302, 307, 308):
                final_url = r.headers['Location']
                if "Authorization" in headers:
                    del headers["Authorization"]
                
                with requests.get(final_url, headers=headers, stream=True) as r2:
                    r2.raise_for_status()
                    with open(filename, 'wb') as f:
                        for chunk in r2.iter_content(chunk_size=8192):
                            f.write(chunk)
            else:
                r.raise_for_status()
                with open(filename, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
                        
        return True
    except Exception as e:
        log(f"Download failed: {e}")
        return False

def get_latest_github_release(repo):
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    try:
        resp = requests.get(url, headers=get_auth_headers())
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        log(f"Failed to fetch release for {repo}: {e}")
        return None

def fetch_tools(source_key):
    config = SOURCES.get(source_key)
    os.makedirs("tools", exist_ok=True)
    
    def get_asset(repo, ext):
        release = get_latest_github_release(repo)
        if not release: return None, None
        
        for asset in release.get('assets', []):
            if asset['name'].endswith(ext) and "source" not in asset['name']:
                if ext == ".jar" and "all" not in asset['name'] and any("all" in a['name'] for a in release['assets']):
                    continue
                return asset['browser_download_url'], asset['name']
        return None, None

    cli_url, cli_name = get_asset(config['cli_repo'], config['cli_asset'])
    if not cli_url: raise Exception(f"Could not find CLI for {source_key}")
    
    cli_path = f"tools/{cli_name}"
    if not os.path.exists(cli_path): download_file(cli_url, cli_path)
    
    patches_url, patches_name = get_asset(config['patches_repo'], config['patches_asset'])
    if not patches_url: raise Exception(f"Could not find Patches for {source_key}")
    
    patches_path = f"tools/{patches_name}"
    if not os.path.exists(patches_path): download_file(patches_url, patches_path)
    
    return cli_path, patches_path

def fetch_apkeditor():
    os.makedirs("tools", exist_ok=True)
    apkeditor_path = "tools/APKEditor.jar"
    # Using v1.4.7 as requested/verified
    if not os.path.exists(apkeditor_path):
        url = "https://github.com/REAndroid/APKEditor/releases/download/V1.4.7/APKEditor-1.4.7.jar"
        if not download_file(url, apkeditor_path):
             raise Exception("Failed to download APKEditor.jar")
    return apkeditor_path

def parse_version_override(override_string, current_app):
    if not override_string or override_string == "auto":
        return "auto"

    if "=" in override_string:
        try:
            overrides = {}
            for part in override_string.split(","):
                key, val = part.split("=")
                overrides[key.strip()] = val.strip()
            return overrides.get(current_app, "auto")
        except:
            log(f"Warning: Failed to parse version override string '{override_string}'. Using auto.")
            return "auto"
    return override_string

def get_target_versions(cli_path, patches_path, package_name, manual_version):
    if manual_version and manual_version != "auto":
        log(f"Manual version override: {manual_version}")
        return [manual_version]
        
    log(f"Auto-detecting versions for {package_name}...")
    cmd = ["java", "-jar", cli_path, "list-versions", patches_path]
    try:
        output = subprocess.check_output(cmd, text=True)
        versions = []
        current_pkg = None
        
        for line in output.splitlines():
            line = line.strip()
            if not line: continue
            
            pkg_match = re.search(r"Package name:\s*([a-zA-Z0-9_.]+)", line)
            if pkg_match:
                current_pkg = pkg_match.group(1)
                continue
                
            if current_pkg == package_name:
                 v_match = re.match(r'^(v?\d+(\.\d+)+)', line)
                 if v_match:
                     versions.append(v_match.group(1))

        if versions:
            versions.sort(key=lambda s: [int(x) for x in s.lstrip('v').split('.') if x.isdigit()], reverse=True)
            log(f"Detected compatible versions: {versions}")
            return versions
            
    except Exception as e:
        log(f"Error detecting version: {e}")
        
    raise Exception(f"Could not determine version automatically for {package_name}")

def strip_monolithic_apk(apk_path):
    """
    PASSTHROUGH: Returns the APK path without modification.
    This prevents corruption of resources in newer apps.
    """
    log(f"Using original APK (skipping strip to prevent corruption): {apk_path}")
    return apk_path 

def merge_bundle(bundle_path, apkeditor_path):
    """
    Directly merges the Bundle using APKEditor.
    Does NOT manually delete files to ensure all language configs are kept.
    """
    log(f"Merging bundle directly: {bundle_path}")
    
    # Create output filename
    output_merged = bundle_path.replace(".apkm", "_merged.apk").replace(".apks", "_merged.apk").replace(".xapk", "_merged.apk")
    if output_merged == bundle_path:
        output_merged = bundle_path + "_merged.apk"

    # Command: java -jar APKEditor.jar m -i input.apkm -o output.apk
    cmd = [
        "java", "-jar", apkeditor_path,
        "m", 
        "-i", bundle_path, 
        "-o", output_merged
    ]
    
    try:
        subprocess.run(cmd, check=True)
        log(f"Merge successful: {output_merged}")
        return output_merged
    except subprocess.CalledProcessError as e:
        raise Exception(f"APKEditor failed to merge bundle: {e}")

def find_apk_in_release(app_name, version):
    log(f"Searching release assets for {app_name} v{version}...")
    release = get_latest_github_release(f"{APK_REPO_OWNER}/{APK_REPO_NAME}")
    if not release: raise Exception("Could not fetch APK repo releases.")
    
    target_base = f"{app_name}-v{version}"
    for asset in release.get('assets', []):
        name = asset['name']
        if name.startswith(target_base) and name.endswith(('.apk', '.apkm', '.apks', '.xapk')):
            return asset['url'], name
    return None, None

def patch_app(app_key, patch_source, input_version_string, cli_path, patches_path):
    pkg = PKG_MAP.get(app_key)
    if not pkg: 
        log(f"Skipping {app_key}: Unknown package map")
        return False

    try:
        app_version_setting = parse_version_override(input_version_string, app_key)
        candidate_versions = get_target_versions(cli_path, patches_path, pkg, app_version_setting)
        
        dl_url = None
        apk_filename = None
        selected_version = None

        for ver in candidate_versions:
            url, name = find_apk_in_release(app_key, ver)
            if url:
                log(f"Found match in repo: {name}")
                dl_url = url
                apk_filename = name
                selected_version = ver
                break
            else:
                log(f"Version {ver} not found in repo, trying next...")
        
        if not dl_url:
            log(f"SKIP: No compatible APKs found in storage repo for {app_key}. Checked: {candidate_versions}")
            return False
            
        os.makedirs("downloads", exist_ok=True)
        local_apk = f"downloads/{apk_filename}"
        if not download_file(dl_url, local_apk):
             raise Exception("Download failed")

        final_apk_path = local_apk
        
        # LOGIC CHANGE: Only use APKEditor if it is a Bundle.
        # If it is a standard APK, we use it directly (via strip_monolithic_apk passthrough).
        if local_apk.endswith((".apkm", ".apks", ".xapk")):
            apkeditor_path = fetch_apkeditor()
            final_apk_path = merge_bundle(local_apk, apkeditor_path)
        else:
            final_apk_path = strip_monolithic_apk(local_apk)

        dist_dir = "dist"
        os.makedirs(dist_dir, exist_ok=True)
        out_apk = f"{dist_dir}/{app_key}-{patch_source}-v{selected_version}-arm64.apk"
        
        cmd = [
            "java", "-jar", cli_path,
            "patch",
            "-p", patches_path,
            "-o", out_apk,
            final_apk_path
        ]
        
        log(f"Patching {app_key}...")
        subprocess.run(cmd, check=True)
        log(f"Successfully created {out_apk}")
        return True

    except Exception as e:
        log(f"FAILED processing {app_key}: {e}")
        return False

def main():
    patch_source = os.environ.get("PATCH_SOURCE")
    apps_input = os.environ.get("APPS_LIST", "all")
    manual_version_input = os.environ.get("VERSION", "auto")

    if not patch_source: 
        print("[!] PATCH_SOURCE env var missing")
        sys.exit(1)

    if apps_input.lower() == "all":
        apps_to_process = list(PKG_MAP.keys())
    else:
        apps_to_process = [x.strip() for x in apps_input.split(",") if x.strip()]

    log(f"Batch Processing: {apps_to_process} using {patch_source}")

    try:
        cli_path, patches_path = fetch_tools(patch_source)
    except Exception as e:
        print(f"[!] Critical: Tool fetch failed - {e}")
        sys.exit(1)

    success_count = 0
    for app in apps_to_process:
        print("\n" + "="*40)
        log(f"Starting {app}...")
        if patch_app(app, patch_source, manual_version_input, cli_path, patches_path):
            success_count += 1
            
    print("\n" + "="*40)
    log(f"Batch completed. Successful builds: {success_count}/{len(apps_to_process)}")
    
    date_str = datetime.now().strftime("%Y.%m.%d")
    tag_name = f"v{date_str}-{patch_source}"
    with open(os.environ['GITHUB_ENV'], 'a') as f:
        f.write(f"RELEASE_TAG={tag_name}\n")
        f.write(f"RELEASE_NAME=ReVanced {patch_source.capitalize()} - {date_str}\n")
    
    if success_count == 0:
        sys.exit(1)

if __name__ == "__main__":
    main()
