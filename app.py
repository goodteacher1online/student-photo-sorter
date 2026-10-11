# -*- coding: utf-8 -*-
"""학생 사진 자동 분류기 데스크톱 앱 (Nothing Design System UI + pywebview)
OpenCV YuNet + SFace 기반 온디바이스 얼굴인식
- 라이트 모드 기본
- 강원교육모두 Bold 타이포그래피
- 100% 오프라인 개인정보 보호
- 비차단(Non-blocking) 상태 폴링 아키텍처로 UI 버벅임 및 무한 대기 현상 완전 방지
"""
from __future__ import annotations

import base64
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Dict, List, Optional

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
elif hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")
elif hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# Qt 백엔드 충돌 원천 차단 (EdgeChromium 전용 보장)
os.environ["PYWEBVIEW_GUI"] = "edgechromium"
for _m in ["PyQt5", "PyQt6", "PySide2", "PySide6"]:
    sys.modules[_m] = None

# 백신 샌드박스 간섭 없는 표준 LOCALAPPDATA 영역에 프로세스별 격리 캐시 지정
local_app = os.environ.get("LOCALAPPDATA", os.path.expanduser("~\\AppData\\Local"))
_wv2_base = os.path.join(local_app, "StudentPhotoSorter")
os.makedirs(_wv2_base, exist_ok=True)
_wv2_data_dir = os.path.join(_wv2_base, f"wv2_{os.getpid()}")
os.makedirs(_wv2_data_dir, exist_ok=True)
os.environ["WEBVIEW2_USER_DATA_FOLDER"] = _wv2_data_dir

import cv2
import webview
from PIL import Image, ImageOps

from engine import FaceSorterEngine, StudentProfile, safe_join, sanitize_filename


def get_asset_dir() -> str:
    """PyInstaller 단일 파일(_MEIPASS) 또는 로컬 소스 코드 에셋 디렉토리"""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return getattr(sys, "_MEIPASS")
    return os.path.dirname(os.path.abspath(__file__))


def get_work_dir() -> str:
    """사용자 실행 파일(.exe)이 위치한 실제 작업 디렉토리"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


class Api:
    def __init__(self, window: Optional[webview.Window] = None):
        self.window: Optional[webview.Window] = window
        self.asset_dir = get_asset_dir()
        self.work_dir = get_work_dir()
        self.models_dir = os.path.join(self.asset_dir, "models")
        self.engine = FaceSorterEngine(self.models_dir)
        self.loaded_students: Dict[str, StudentProfile] = {}

        # 스레드 안전한 실시간 계측 상태 버퍼 (JS 폴링 연동)
        self._state_lock = threading.Lock()
        self.log_queue: List[str] = []
        self.sorting_state: Dict[str, Any] = {
            "status": "idle",  # idle, running, completed, cancelled, error
            "current": 0,
            "total": 0,
            "filename": "",
            "items_per_second": 0.0,
            "stats": {
                "total_scanned": 0,
                "classified_count": 0,
                "multi_person_count": 0,
                "unclassified_count": 0,
                "student_matches": {},
                "elapsed_seconds": 0.0,
            },
        }

    def set_window(self, window: webview.Window) -> None:
        self.window = window

    def get_system_info(self) -> Dict[str, Any]:
        """시스템 및 엔진 상태 반환"""
        sample_profile = os.path.join(self.work_dir, "sample_data", "학생_기준_사진")
        sample_target = os.path.join(self.work_dir, "sample_data", "분류_대상_사진")
        sample_output = os.path.join(self.work_dir, "sample_data", "분류_결과")

        default_dirs = {}
        if os.path.exists(sample_profile):
            default_dirs["profile_dir"] = sample_profile
        if os.path.exists(sample_target):
            default_dirs["target_dir"] = sample_target
        if os.path.exists(sample_output):
            default_dirs["output_dir"] = sample_output

        return {
            "opencv_version": cv2.__version__,
            "models_ready": True,
            "default_dirs": default_dirs,
        }

    def select_folder(self, title: str = "폴더 선택") -> Optional[str]:
        """독립 실행형 exe 환경에서도 100% 동작하는 네이티브 폴더 선택 다이얼로그
        1. pywebview 내장 create_file_dialog 우선 시도
        2. PowerShell .NET FolderBrowserDialog 독립 서브프로세스 폴백
        """
        if self.window is not None:
            try:
                res = self.window.create_file_dialog(webview.FOLDER_DIALOG)
                if res and len(res) > 0:
                    return os.path.normpath(res[0])
            except Exception:
                pass

        ps_cmd = (
            "[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null; "
            "$f = New-Object System.Windows.Forms.FolderBrowserDialog; "
            f"$f.Description = '{title}'; "
            "$f.ShowNewFolderButton = $true; "
            "if ($f.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { Write-Output $f.SelectedPath }"
        )
        try:
            res = subprocess.check_output(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
                text=True,
                creationflags=0x08000000,  # CREATE_NO_WINDOW
                timeout=120,
            ).strip()
            return os.path.normpath(res) if res else None
        except Exception as e:
            print("Folder dialog error:", e)
            return None

    def scan_student_profiles(self, profile_dir: str) -> Dict[str, Any]:
        """학생 기준 폴더 내 메타데이터를 초경량(0.01초)으로 스캔하여 UI에 즉시 반환
        - 얼굴인식 ONNX 추론을 전혀 거치지 않아 창 멈춤/응답 없음 원천 차단
        - 첫 번째 사진 썸네일만 초소형으로 인코딩
        """
        if not profile_dir or not os.path.exists(profile_dir):
            return {"students": [], "logs": ["지정한 폴더를 찾을 수 없습니다."]}

        clean_profile_dir = os.path.abspath(profile_dir)
        folder_infos = FaceSorterEngine.scan_student_folders(clean_profile_dir)

        result = []
        for info in folder_infos:
            thumb_b64 = None
            first_img = info.get("first_img_path")
            if first_img and os.path.exists(first_img):
                try:
                    with Image.open(first_img) as pil_img:
                        pil_img = ImageOps.exif_transpose(pil_img)
                        pil_img.thumbnail((80, 80))
                        if pil_img.mode != "RGB":
                            pil_img = pil_img.convert("RGB")
                        buf = io.BytesIO()
                        pil_img.save(buf, format="JPEG", quality=75)
                        encoded = base64.b64encode(buf.getvalue()).decode("utf-8")
                        thumb_b64 = f"data:image/jpeg;base64,{encoded}"
                except Exception:
                    pass

            result.append({
                "name": info["name"],
                "count": info["count"],
                "preview_thumb": thumb_b64,
            })

        log_msg = f"학생 명단 {len(result)}명 확인 완료 (기준 사진 총 {sum(r['count'] for r in result)}장)"
        return {"students": result, "logs": [log_msg]}

    def add_student(self, profile_dir: str, student_name: str) -> Dict[str, Any]:
        """새 학생 폴더 생성"""
        try:
            name = FaceSorterEngine.create_student_folder(profile_dir, student_name)
            return {"success": True, "name": name, "message": f"'{name}' 학생이 새로 등록되었습니다."}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def delete_student(self, profile_dir: str, student_name: str) -> Dict[str, Any]:
        """학생 및 기준 사진 폴더 삭제"""
        try:
            ok = FaceSorterEngine.delete_student_folder(profile_dir, student_name)
            if ok:
                return {"success": True, "message": f"'{student_name}' 학생이 삭제되었습니다."}
            return {"success": False, "error": "해당 학생 폴더를 찾을 수 없습니다."}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def rename_student(self, profile_dir: str, old_name: str, new_name: str) -> Dict[str, Any]:
        """학생 폴더명 변경"""
        try:
            name = FaceSorterEngine.rename_student_folder(profile_dir, old_name, new_name)
            return {"success": True, "name": name, "message": f"학생 이름이 '{name}'(으)로 변경되었습니다."}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_student_detail(self, profile_dir: str, student_name: str) -> Dict[str, Any]:
        """학생의 모든 기준 사진 및 썸네일 상세 조회"""
        try:
            photos = FaceSorterEngine.list_student_photos(profile_dir, student_name)
            photo_details = []
            for p in photos:
                thumb_b64 = None
                if os.path.exists(p["path"]):
                    try:
                        with Image.open(p["path"]) as pil_img:
                            pil_img = ImageOps.exif_transpose(pil_img)
                            pil_img.thumbnail((160, 160))
                            if pil_img.mode != "RGB":
                                pil_img = pil_img.convert("RGB")
                            buf = io.BytesIO()
                            pil_img.save(buf, format="JPEG", quality=80)
                            encoded = base64.b64encode(buf.getvalue()).decode("utf-8")
                            thumb_b64 = f"data:image/jpeg;base64,{encoded}"
                    except Exception:
                        pass
                photo_details.append({
                    "filename": p["filename"],
                    "path": p["path"],
                    "size_kb": p["size_kb"],
                    "thumb": thumb_b64,
                })
            return {"success": True, "name": student_name, "photos": photo_details}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def select_images(self, title: str = "사진 파일 선택") -> List[str]:
        """이미지 파일 다중 선택 다이얼로그 (네이티브 & PowerShell 폴백)"""
        if self.window is not None:
            try:
                res = self.window.create_file_dialog(
                    webview.OPEN_DIALOG,
                    allow_multiple=True,
                    file_types=("이미지 파일 (*.jpg;*.jpeg;*.png;*.webp;*.bmp)", "모든 파일 (*.*)"),
                )
                if res and len(res) > 0:
                    return [os.path.normpath(f) for f in res]
            except Exception:
                pass

        ps_cmd = (
            "[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null; "
            "$f = New-Object System.Windows.Forms.OpenFileDialog; "
            f"$f.Title = '{title}'; "
            "$f.Multiselect = $true; "
            "$f.Filter = '이미지 파일|*.jpg;*.jpeg;*.png;*.webp;*.bmp|모든 파일|*.*'; "
            "if ($f.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { $f.FileNames | ForEach-Object { Write-Output $_ } }"
        )
        try:
            res = subprocess.check_output(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
                text=True,
                creationflags=0x08000000,
                timeout=120,
            ).strip().splitlines()
            return [os.path.normpath(f.strip()) for f in res if f.strip()]
        except Exception:
            return []

    def add_student_photos(self, profile_dir: str, student_name: str, file_paths: List[str]) -> Dict[str, Any]:
        """학생에게 새 기준 사진 파일들 추가"""
        try:
            count = FaceSorterEngine.add_photos_to_student(profile_dir, student_name, file_paths)
            return {"success": True, "added_count": count, "message": f"{count}장의 기준 사진이 추가되었습니다."}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def delete_student_photo(self, profile_dir: str, student_name: str, filename: str) -> Dict[str, Any]:
        """학생의 특정 기준 사진 삭제"""
        try:
            ok = FaceSorterEngine.delete_student_photo_file(profile_dir, student_name, filename)
            if ok:
                return {"success": True, "message": f"'{filename}' 사진이 삭제되었습니다."}
            return {"success": False, "error": "해당 사진 파일을 찾을 수 없습니다."}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def move_student_photo(self, profile_dir: str, from_student: str, to_student: str, filename: str) -> Dict[str, Any]:
        """특정 학생의 기준 사진을 다른 학생에게 이동"""
        try:
            ok = FaceSorterEngine.move_student_photo_file(profile_dir, from_student, to_student, filename)
            if ok:
                return {"success": True, "message": f"'{filename}' 사진을 '{to_student}' 학생에게 이동했습니다."}
            return {"success": False, "error": "사진 이동에 실패했습니다."}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def open_student_folder(self, profile_dir: str, student_name: str) -> bool:
        """해당 학생의 기준 폴더를 Windows 탐색기로 열기"""
        clean_name = sanitize_filename(student_name)
        folder = safe_join(profile_dir, clean_name)
        return self.open_folder(folder)

    def start_sorting(self, params: Dict[str, Any]) -> None:
        """백그라운드 스레드에서 안전하게 사진 분류 실행"""
        threading.Thread(target=self._run_sorting_worker, args=(params,), daemon=True).start()

    def _run_sorting_worker(self, params: Dict[str, Any]) -> None:
        with self._state_lock:
            self.log_queue.clear()
            self.sorting_state = {
                "status": "running",
                "current": 0,
                "total": 0,
                "filename": "",
                "items_per_second": 0.0,
                "stats": {
                    "total_scanned": 0,
                    "classified_count": 0,
                    "multi_person_count": 0,
                    "unclassified_count": 0,
                    "student_matches": {},
                    "elapsed_seconds": 0.0,
                },
            }

        target_dir = os.path.abspath(params.get("target_dir", ""))
        profile_dir = os.path.abspath(params.get("profile_dir", ""))
        output_dir = os.path.abspath(params.get("output_dir", ""))
        threshold = float(params.get("threshold", 0.40))
        copy_multi = bool(params.get("copy_multi", True))
        keep_original = bool(params.get("keep_original", True))

        def log_cb(msg: str):
            with self._state_lock:
                self.log_queue.append(msg)

        def progress_cb(current: int, total: int, filename: str, stats):
            with self._state_lock:
                self.sorting_state["current"] = current
                self.sorting_state["total"] = total
                self.sorting_state["filename"] = filename
                self.sorting_state["items_per_second"] = stats.items_per_second
                self.sorting_state["stats"] = {
                    "total_scanned": stats.total_scanned,
                    "classified_count": stats.classified_count,
                    "multi_person_count": stats.multi_person_count,
                    "unclassified_count": stats.unclassified_count,
                    "student_matches": stats.student_matches,
                    "elapsed_seconds": round(stats.elapsed_seconds, 2),
                }

        try:
            log_cb("🔍 학생 기준 사진 및 얼굴 특징 벡터 분석 중...")
            self.loaded_students = self.engine.load_students(profile_dir, log_cb=log_cb)

            if not self.loaded_students:
                raise ValueError("기준 얼굴 특징이 확보된 학생이 없습니다. 학생 폴더에 선명한 사진을 넣어주세요.")

            log_cb(f"총 {len(self.loaded_students)}명의 얼굴 기준 특징 확보 완료. 분류를 시작합니다...")

            stats = self.engine.sort_photos(
                target_dir=target_dir,
                output_dir=output_dir,
                students=self.loaded_students,
                threshold=threshold,
                copy_multi_person=copy_multi,
                keep_original=keep_original,
                progress_cb=progress_cb,
                log_cb=log_cb,
            )
            with self._state_lock:
                self.sorting_state["status"] = "cancelled" if self.engine.is_cancelled else "completed"
                self.sorting_state["stats"] = {
                    "total_scanned": stats.total_scanned,
                    "classified_count": stats.classified_count,
                    "multi_person_count": stats.multi_person_count,
                    "unclassified_count": stats.unclassified_count,
                    "student_matches": stats.student_matches,
                    "elapsed_seconds": round(stats.elapsed_seconds, 2),
                }
        except Exception as e:
            with self._state_lock:
                self.sorting_state["status"] = "error"
                self.log_queue.append(f"❌ 오류 발생: {e}")

    def get_sorting_state(self) -> Dict[str, Any]:
        """JS 클라이언트가 100~150ms마다 비동기 호출하는 무중단 상태 폴링 API"""
        with self._state_lock:
            logs = list(self.log_queue)
            self.log_queue.clear()
            return {
                "state": dict(self.sorting_state),
                "logs": logs,
            }

    def cancel_sorting(self) -> None:
        """작업 즉시 중단"""
        self.engine.is_cancelled = True

    def open_folder(self, path: str) -> bool:
        """탐색기에서 해당 폴더 열기"""
        if not path:
            return False
        clean_path = os.path.abspath(path)
        if not os.path.exists(clean_path):
            os.makedirs(clean_path, exist_ok=True)
        try:
            os.startfile(clean_path)
            return True
        except Exception as e:
            print("open_folder error:", e)
            return False

    def create_sample_dataset(self) -> Dict[str, str]:
        """테스트용 샘플 디렉토리 구조 및 안내 생성"""
        sample_base = os.path.join(self.base_dir, "sample_data")
        profile_dir = os.path.join(sample_base, "학생_기준_사진")
        target_dir = os.path.join(sample_base, "분류_대상_사진")
        output_dir = os.path.join(sample_base, "분류_결과")

        sample_students = ["김민준", "이서아", "박도윤"]
        for s in sample_students:
            s_folder = os.path.join(profile_dir, s)
            os.makedirs(s_folder, exist_ok=True)
            readme_path = os.path.join(s_folder, f"{s}_정면사진을_넣어주세요.txt")
            if not os.path.exists(readme_path):
                with open(readme_path, "w", encoding="utf-8") as f:
                    f.write(f"{s} 학생의 정면 얼굴 사진(JPG/PNG)을 1~2장 넣어주세요.\n")

        os.makedirs(target_dir, exist_ok=True)
        os.makedirs(output_dir, exist_ok=True)

        target_readme = os.path.join(target_dir, "분류할_활동사진을_넣어주세요.txt")
        if not os.path.exists(target_readme):
            with open(target_readme, "w", encoding="utf-8") as f:
                f.write("선생님이 찍으신 행사/놀이/수업 사진들을 여기에 모아 넣어주세요.\n")

        return {
            "profile_dir": profile_dir,
            "target_dir": target_dir,
            "output_dir": output_dir,
        }


def log_debug(msg: str):
    try:
        log_path = os.path.join(tempfile.gettempdir(), "student_sorter_debug.log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass


def main():
    log_debug("--- [앱 시작 진입] ---")
    try:
        asset_dir = get_asset_dir()
        html_path = os.path.join(asset_dir, "index.html")
        log_debug(f"asset_dir: {asset_dir}")
        log_debug(f"html_path: {html_path} (exists: {os.path.exists(html_path)})")

        api = Api()
        url_target = f"file:///{os.path.abspath(html_path).replace(os.sep, '/')}"
        log_debug(f"url_target: {url_target}")
        window = webview.create_window(
            title="학생 사진 자동 분류기 — Nothing Design System",
            url=url_target,
            width=1400,
            height=940,
            min_size=(1020, 700),
            js_api=api,
        )
        api.set_window(window)

        def on_closed():
            log_debug("창 종료 이벤트 감지 -> 프로세스 종료")
            try:
                import shutil
                shutil.rmtree(_wv2_data_dir, ignore_errors=True)
            except Exception:
                pass
            os._exit(0)

        window.events.closed += on_closed
        log_debug("webview.start(gui='edgechromium') 호출 직전")
        webview.start(gui="edgechromium", debug=False, private_mode=False)
        log_debug("webview.start 정상 종료")
    except Exception as e:
        import traceback
        err_msg = traceback.format_exc()
        log_debug(f"CRITICAL ERROR: {err_msg}")
        # 오류 발생 시 사용자 알림 다이얼로그 표시
        try:
            code = (
                "[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null; "
                f"[System.Windows.Forms.MessageBox]::Show('앱 실행 중 오류가 발생했습니다:\\n{e}', '학생 사진 자동 분류기 오류', 'OK', 'Error')"
            )
            subprocess.run(["powershell", "-NoProfile", "-Command", code])
        except Exception:
            pass


if __name__ == "__main__":
    main()
