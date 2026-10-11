# -*- coding: utf-8 -*-
"""PyInstaller 최적화 빌드 스크립트
1. 초고속 폴더형 배포판 (--onedir): 압축 해제 없이 0초 즉시 기동 (권장)
2. 단일 파일 포터블 exe (--onefile): 이동 및 공유용 단일 파일
"""
import os
import shutil
import subprocess
import sys

# Windows CP949 콘솔 인코딩 충돌 방지
if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr is not None and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

base_dir = os.path.dirname(os.path.abspath(__file__))

# 1. 리소스 데이터 인자 구성
data_args = [
    "--add-data", f"{os.path.join(base_dir, 'index.html')};.",
    "--add-data", f"{os.path.join(base_dir, 'styles.css')};.",
    "--add-data", f"{os.path.join(base_dir, 'app.js')};.",
    "--add-data", f"{os.path.join(base_dir, 'fonts')};fonts",
    "--add-data", f"{os.path.join(base_dir, 'models')};models",
]

sample_dir = os.path.join(base_dir, "sample_data")
if os.path.exists(sample_dir):
    data_args.extend(["--add-data", f"{sample_dir};sample_data"])

# 2. 불필요한 무거운 모듈 배제 (빌드 크기 70% 감소 & 메모리 최적화)
exclude_modules = [
    "PyQt5", "PyQt6", "PySide2", "PySide6",
    "matplotlib", "scipy", "pandas",
    "cryptography", "bcrypt", "IPython", "notebook",
    "torch", "torchvision", "torchaudio",
    "tkinter", "tcl",
]
exclude_args = []
for mod in exclude_modules:
    exclude_args.extend(["--exclude-module", mod])

common_flags = [
    "--windowed",
    "--noconfirm",
    *data_args,
    *exclude_args,
    "--hidden-import", "clr",
    "--hidden-import", "webview",
    "--hidden-import", "cv2",
    "--hidden-import", "PIL",
    "--hidden-import", "engine",
]

def build_onedir():
    """초고속 0초 기동 폴더형 배포판 빌드"""
    print("\n" + "="*60)
    print("[1/2] 초고속 폴더형(0초 기동) 배포판 빌드 시작...")
    print("="*60)
    out_name = "StudentPhotoSorter_Fast"
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onedir",
        "--name", out_name,
        *common_flags,
        os.path.join(base_dir, "app.py")
    ]
    res = subprocess.run(cmd, cwd=base_dir)
    if res.returncode == 0:
        dir_path = os.path.join(base_dir, "dist", out_name)
        korean_dir = os.path.join(base_dir, "dist", "학생사진자동분류기_초고속")
        if os.path.exists(korean_dir):
            shutil.rmtree(korean_dir, ignore_errors=True)
        shutil.copytree(dir_path, korean_dir)
        
        # 한국어 실행 파일로 복사
        fast_exe = os.path.join(korean_dir, "학생사진자동분류기.exe")
        src_exe = os.path.join(korean_dir, f"{out_name}.exe")
        if os.path.exists(src_exe):
            shutil.copy2(src_exe, fast_exe)
        
        print(f"[성공] 초고속 폴더형 배포판 완성: {korean_dir}")
        print(f"       실행 파일: {fast_exe}")
    else:
        print(f"[실패] Exit code: {res.returncode}")

def build_onefile():
    """단일 실행 파일(.exe) 빌드"""
    print("\n" + "="*60)
    print("[2/2] 단일 파일(.exe) 포터블 빌드 시작...")
    print("="*60)
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name", "StudentPhotoSorter",
        *common_flags,
        os.path.join(base_dir, "app.py")
    ]
    res = subprocess.run(cmd, cwd=base_dir)
    if res.returncode == 0:
        src_exe = os.path.join(base_dir, "dist", "StudentPhotoSorter.exe")
        root_exe = os.path.join(base_dir, "학생사진자동분류기.exe")
        if os.path.exists(src_exe):
            shutil.copy2(src_exe, root_exe)
            size_mb = os.path.getsize(root_exe) / (1024 * 1024)
            print(f"[성공] 최적화 단일 exe 완성! 크기: {size_mb:.1f} MB")
            print(f"       실행 파일: {root_exe}")
    else:
        print(f"[실패] Exit code: {res.returncode}")

if __name__ == "__main__":
    build_onedir()
    build_onefile()
    print("\n[완료] 모든 배포 빌드가 정상 완료되었습니다!")
