import os
import sys
import json
import requests
import re
import zipfile
import shutil
import subprocess
from bs4 import BeautifulSoup

# --- Configuration ---
# You can add more mirrors here if needed
SOURCES = [
    "apkpure",
    "apkmirror" 
]

# Standard User-Agent to avoid 403s on some sites
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

def log(msg):
    print(f"[+] {msg}", flush=True)

def error(msg):
    print(f"[!] {msg}", flush=True)
    sys.exit(1)

def download_file(url, filename):
    log(f"Downloading {url} -> {filename}")
    with requests.get(url, stream=True, headers=HEADERS) as r:
        r.raise_for_status()
        with open(filename, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
    return filename

def get_latest_github_release(repo):
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    resp = requests.get(url).json()
    return resp

def fetch_revanced_tools():
    """Downloads the latest CLI and Patches (RVP) from official repos."""
    os.makedirs("tools", exist_ok=True)
    
    # 1. Fetch CLI
    cli_release = get_latest_github_release("ReVanced/revanced-cli")
    cli_asset = next(a for a in cli_release['assets'] if a['name'].endswith('.jar'))
    cli_path = f"tools/{cli_asset['name']}"
    if not os.path.exists(cli_path):
        download_file(cli_asset['browser_download_url'], cli_path)
    
    # 2. Fetch Patches (RVP)
    patches_release = get_latest_github_release("ReVanced/revanced-patches")
    # Find the .rvp file
    patches_rvp_asset = next(a for a in patches_release['assets'] if a['name'].endswith('.rvp'))
    
    patches_rvp_path = f"tools/{patches_rvp_asset['name']}"
    
    if not os.path.exists(patches_rvp_path):
        download_file(patches_rvp_asset['browser_download_url'], patches_rvp_path)
        
    return cli_path, patches_rvp_path

def get_compatible_version(package_name, cli_path, patches_rvp_path, manual_version=None):
    if manual_version and manual_version != "auto":
        log(f"Manual version override: {manual_version}")
        return manual_version

    log(f"Finding compatible version for {package_name} using CLI...")
    
    # Run the CLI to list patches and their compatibility
    # Command: java -jar cli.jar list-patches --with-packages --with-versions patches.rvp
    cmd = [
        "java", "-jar", cli_path, 
        "list-patches", 
        "--with-packages", "--with-versions", 
        patches_rvp_path
    ]
    
    try:
        # Capture stdout
        result = subprocess.check_output(cmd, text=True)
    except subprocess.CalledProcessError as e:
        error(f"Failed to list patches: {e}")
        return None

    # Parse the output
    # The output format is typically human readable. 
    # We look for the package name and associated versions.
    # Pattern might look like: com.google.android.youtube (19.16.38, 19.16.39)
    # We will regex for the package name, then capture the text inside parentheses immediately following it.
    
    versions = set()
    
    # Regex to find: package.name followed optionally by versions in parentheses
    # Example hit: com.google.android.youtube (19.04.37)
    # Note: The output format can vary, so we try to be robust.
    # We search for lines containing the package name.
    
    lines = result.splitlines()
    for line in lines:
        if package_name in line:
            # check for versions in parentheses: (v1, v2)
            match = re.search(r'\(([\d\.,\s]+)\)', line)
            if match:
                v_str = match.group(1)
                # Split by comma or space
                found_vs = [v.strip() for v in re.split(r'[,\s]+', v_str) if v.strip()]
                versions.update(found_vs)

    if not versions:
        log("No specific compatible versions found in CLI output. Using 'latest' logic (risky).")
        # In automation, sometimes it's better to fail than to build a broken APK.
        # But we'll return None to trigger fail-safe or manual usage.
        return None

    # Sort versions
    def version_key(v):
        # Handle cases where version might not be purely numeric
        try:
            return [int(x) for x in v.split('.')]
        except ValueError:
            return [0]
    
    sorted_versions = sorted(list(versions), key=version_key, reverse=True)
    
    # Filter out extremely old versions if necessary, but taking the top 1 is usually safe
    best_version = sorted_versions[0]
    log(f"Latest compatible version found: {best_version}")
    return best_version

# --- Scraper Functions ---

def scrape_apkpure(package_name, app_name, version):
    """
    Scrapes APKPure for the specific version.
    Returns: path to downloaded file or None.
    """
    log(f"Searching APKPure for {app_name} v{version}...")
    query = f"{app_name} {version}"
    search_url = f"https://apkpure.net/search?q={query}"
    
    try:
        r = requests.get(search_url, headers=HEADERS)
        soup = BeautifulSoup(r.text, 'html.parser')
        
        # Find the first result link
        first_result = soup.select_one(".first-mobile-out a")
        if not first_result:
             first_result = soup.select_one(".dd a") # Fallback selector
        
        if not first_result:
            log("APKPure: No results found.")
            return None

        app_link = first_result['href']
        if not app_link.startswith("http"):
            app_link = "https://apkpure.net" + app_link

        download_page_url = app_link + "/download"
        
        log(f"Checking details at {app_link}")
        
        # Download logic
        r_dl = requests.get(download_page_url, headers=HEADERS)
        soup_dl = BeautifulSoup(r_dl.text, 'html.parser')
        
        download_link = soup_dl.select_one("#download_link")
        if download_link:
            href = download_link['href']
            filename = f"downloads/{package_name}_{version}.apk"
            download_file(href, filename)
            return filename
            
    except Exception as e:
        log(f"APKPure failed: {e}")
        return None

def scrape_apkmirror(package_name, app_name, version):
    """
    Scrapes APKMirror.
    """
    log(f"Searching APKMirror for {app_name} v{version}...")
    search_query = f"{app_name} {version}"
    url = f"https://www.apkmirror.com/?post_type=app_release&searchtype=apk&s={search_query}"
    
    try:
        r = requests.get(url, headers=HEADERS)
        if r.status_code == 403:
            log("APKMirror blocked request (403). Skipping.")
            return None
            
        soup = BeautifulSoup(r.text, 'html.parser')
        
        rows = soup.select(".appRow")
        target_url = None
        
        for row in rows:
            text = row.get_text()
            if version in text:
                link = row.select_one("a.downloadLink")['href']
                target_url = "https://www.apkmirror.com" + link
                break
        
        if not target_url:
            return None
            
        log("APKMirror link found, but deep scraping requires bypassing Cloudflare/Bot detection. Skipping to ensure workflow stability.")
        return None 

    except Exception as e:
        log(f"APKMirror failed: {e}")
        return None

# --- Main Logic ---

def download_apk(package_name, app_name, version):
    os.makedirs("downloads", exist_ok=True)
    
    # Try Sources in order
    downloaded_path = scrape_apkpure(package_name, app_name, version)
    
    if not downloaded_path:
        downloaded_path = scrape_apkmirror(package_name, app_name, version)
        
    if not downloaded_path:
        error(f"Could not download APK for {app_name} v{version} from any source.")
        
    return downloaded_path

def process_apk(apk_path):
    """
    Handles Bundles (.apkm, .xapk) or Split APKs.
    Returns a list of files to pass to the patcher.
    """
    ext = os.path.splitext(apk_path)[1].lower()
    
    if ext in ['.apk']:
        return [apk_path]
    
    log(f"Detected bundle {ext}. Extracting...")
    extract_dir = "extracted_apk"
    if os.path.exists(extract_dir):
        shutil.rmtree(extract_dir)
    os.makedirs(extract_dir)
    
    with zipfile.ZipFile(apk_path, 'r') as zip_ref:
        zip_ref.extractall(extract_dir)
        
    # Find Base and Architecture Split
    files = []
    # Logic for XAPK / APKM (usually just a zip of APKs)
    for root, dirs, filenames in os.walk(extract_dir):
        for f in filenames:
            if f.endswith(".apk"):
                # We need base.apk and the arm64 split
                if "x86" in f or "armeabi-v7a" in f:
                    continue # Skip wrong arch
                files.append(os.path.join(root, f))
                
    log(f"Extracted files for patching: {files}")
    return files

def main():
    package_name = os.environ.get("PACKAGE_NAME")
    app_name = os.environ.get("APP_NAME")
    manual_version = os.environ.get("VERSION", "auto")
    
    if not package_name or not app_name:
        error("PACKAGE_NAME or APP_NAME env vars missing")

    # 1. Setup Tools
    cli_path, patches_rvp_path = fetch_revanced_tools()
    
    # 2. Determine Version
    target_version = get_compatible_version(package_name, cli_path, patches_rvp_path, manual_version)
    if not target_version:
        error("Could not determine target version.")
        
    # 3. Download
    raw_apk_path = download_apk(package_name, app_name, target_version)
    
    # 4. Prepare inputs (Handle Splits)
    input_files = process_apk(raw_apk_path)
    
    # 5. Patch
    output_apk = f"build/{app_name.replace(' ', '-')}-ReVanced-v{target_version}.apk"
    os.makedirs("build", exist_ok=True)
    
    # Construct Command
    # java -jar cli.jar patch -p patches.rvp -o out.apk input1.apk input2.apk ...
    cmd = [
        "java", "-jar", cli_path,
        "patch",
        "-p", patches_rvp_path,
        "-o", output_apk,
    ]
    # Add all input files (base + splits)
    cmd.extend(input_files)
    
    log(f"Running Patcher: {' '.join(cmd)}")
    try:
        subprocess.run(cmd, check=True)
        log(f"Patching successful! Output: {output_apk}")
        
        # Write output filename to GITHUB_ENV for the next step
        with open(os.environ['GITHUB_ENV'], 'a') as f:
            f.write(f"PATCHED_APK={output_apk}\n")
            f.write(f"APP_VERSION={target_version}\n")
            
    except subprocess.CalledProcessError as e:
        error(f"Patching failed: {e}")

if __name__ == "__main__":
    main()
