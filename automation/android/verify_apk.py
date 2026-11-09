#!/usr/bin/env python3
"""Verify a Project Aussie APK really contains the complete game.

Checks, using only real data from the APK file:
  * assets/index.html is present;
  * every file in www/ (minus editor backups / OS junk) is in the APK under
    assets/ with an identical CRC-32 (byte-for-byte check via the zip index);
  * no unexpected extra files were packaged under assets/;
  * the package name (read with aapt2 from the build-tools) equals --expect-package.
Writes a JSON summary (--json) for the daily report. Exit code 1 on any failure.
"""
import argparse, fnmatch, json, os, subprocess, sys, zipfile, zlib, glob, shutil

EXCLUDES = ['index.*.bak.html', '.DS_Store', 'Thumbs.db', 'desktop.ini']


def www_files(www):
    out = {}
    for root, _, files in os.walk(www):
        for f in files:
            if any(fnmatch.fnmatch(f, p) for p in EXCLUDES):
                continue
            full = os.path.join(root, f)
            rel = os.path.relpath(full, www).replace(os.sep, '/')
            with open(full, 'rb') as fh:
                out[rel] = zlib.crc32(fh.read()) & 0xffffffff
    return out


def find_aapt2():
    sdk = os.environ.get('ANDROID_HOME') or os.environ.get('ANDROID_SDK_ROOT') or ''
    cands = sorted(glob.glob(os.path.join(sdk, 'build-tools', '*', 'aapt2')))
    if cands:
        return cands[-1]
    return shutil.which('aapt2')


def package_name(apk):
    aapt2 = find_aapt2()
    if not aapt2:
        return None, 'aapt2 not found (set ANDROID_HOME)'
    r = subprocess.run([aapt2, 'dump', 'badging', apk], capture_output=True, text=True)
    for line in r.stdout.splitlines():
        if line.startswith('package:'):
            parts = dict(p.split('=', 1) for p in line[len('package: '):].split() if '=' in p)
            return {k: v.strip("'") for k, v in parts.items()}, None
    return None, 'aapt2 badging had no package line: ' + r.stderr[:300]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('apk')
    ap.add_argument('--www', default='www')
    ap.add_argument('--expect-package', required=True)
    ap.add_argument('--json')
    a = ap.parse_args()

    errors = []
    src = www_files(a.www)
    with zipfile.ZipFile(a.apk) as z:
        apk_assets = {i.filename[len('assets/'):]: i.CRC for i in z.infolist()
                      if i.filename.startswith('assets/') and not i.is_dir()}
    if 'index.html' not in apk_assets:
        errors.append('assets/index.html is missing from the APK')
    missing = sorted(set(src) - set(apk_assets))
    extra = sorted(set(apk_assets) - set(src))
    mismatch = sorted(k for k in set(src) & set(apk_assets) if src[k] != apk_assets[k])
    if missing:
        errors.append(f'{len(missing)} game file(s) missing from APK, e.g. {missing[:5]}')
    if extra:
        errors.append(f'{len(extra)} unexpected file(s) under assets/, e.g. {extra[:5]}')
    if mismatch:
        errors.append(f'{len(mismatch)} file(s) differ from www/, e.g. {mismatch[:5]}')
    pkg, perr = package_name(a.apk)
    if perr:
        errors.append(perr)
    elif pkg.get('name') != a.expect_package:
        errors.append(f"package is {pkg.get('name')!r}, expected {a.expect_package!r}")

    summary = {
        'apk': os.path.basename(a.apk), 'apk_bytes': os.path.getsize(a.apk),
        'www_files': len(src), 'apk_asset_files': len(apk_assets),
        'missing': len(missing), 'extra': len(extra), 'crc_mismatch': len(mismatch),
        'package': (pkg or {}).get('name'), 'versionName': (pkg or {}).get('versionName'),
        'versionCode': (pkg or {}).get('versionCode'),
        'ok': not errors, 'errors': errors,
    }
    print(json.dumps(summary, indent=2))
    if a.json:
        with open(a.json, 'w') as fh:
            json.dump(summary, fh, indent=2)
    if errors:
        for e in errors:
            print(f'::error::{e}')
        sys.exit(1)


if __name__ == '__main__':
    main()
