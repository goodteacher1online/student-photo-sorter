# -*- coding: utf-8 -*-
"""학생 사진 자동 분류 엔진 (OpenCV YuNet + SFace 기반)
- 100% 온디바이스 로컬 오프라인 구동 (외부 클라우드 전송 없음)
- EXIF 촬영 각도 자동 회전 보정 (스마트폰 촬영 사진 최적화)
- 경로 순회(Path Traversal) 공격 방지 및 파일 덮어쓰기 방지 안전 복사
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
elif hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")
elif hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

import cv2
import numpy as np
from PIL import Image, ImageOps


def sanitize_filename(name: str) -> str:
    """Windows 파일명 및 폴더명으로 사용할 수 없는 특수문자 및 마침표(.) 정제"""
    cleaned = re.sub(r'[\\/*?:"<>|]', "", name).strip(" .\t\r\n")
    cleaned = re.sub(r'\.{2,}', "", cleaned).strip(" .\t\r\n")
    return cleaned if cleaned else "무명"


def safe_join(base: str, *paths: str) -> str:
    """경로 순회(Path Traversal)를 방지하는 안전한 경로 결합"""
    full_path = os.path.abspath(os.path.join(base, *paths))
    base_abs = os.path.abspath(base)
    if os.path.commonpath([base_abs, full_path]) != base_abs:
        raise ValueError(f"비정상적인 접근 경로가 감지되었습니다: {full_path}")
    return full_path


def get_unique_destination_path(target_dir: str, filename: str) -> str:
    """동일한 파일명이 존재할 경우 _1, _2 접미사를 붙여 원본 덮어쓰기 방지"""
    name, ext = os.path.splitext(filename)
    dest_path = os.path.join(target_dir, filename)
    counter = 1
    while os.path.exists(dest_path):
        new_filename = f"{name}_{counter}{ext}"
        dest_path = os.path.join(target_dir, new_filename)
        counter += 1
    return dest_path


@dataclass
class StudentProfile:
    name: str
    folder_path: str
    image_count: int = 0
    features: List[np.ndarray] = field(default_factory=list)
    preview_thumb: Optional[str] = None


@dataclass
class SortStats:
    total_scanned: int = 0
    classified_count: int = 0
    multi_person_count: int = 0
    unclassified_count: int = 0
    student_matches: Dict[str, int] = field(default_factory=dict)
    elapsed_seconds: float = 0.0
    items_per_second: float = 0.0


class FaceSorterEngine:
    def __init__(self, models_dir: str):
        self.models_dir = os.path.abspath(models_dir)
        self.detector_path = os.path.join(self.models_dir, "face_detection_yunet_2023mar.onnx")
        self.recognizer_path = os.path.join(self.models_dir, "face_recognition_sface_2021dec.onnx")

        self.detector: Optional[cv2.FaceDetectorYN] = None
        self.recognizer: Optional[cv2.FaceRecognizerSF] = None
        self.is_cancelled = False

    def ensure_models_loaded(self) -> None:
        """모델이 아직 로드되지 않은 경우에만 지연 로딩(Lazy Loading)으로 초기화"""
        if self.detector is not None and self.recognizer is not None:
            return

        if not os.path.exists(self.detector_path) or not os.path.exists(self.recognizer_path):
            raise FileNotFoundError(f"모델 파일이 존재하지 않습니다: {self.models_dir}")

        # YuNet: 초경량 고속 얼굴 검출 (score_threshold=0.6, nms_threshold=0.3)
        self.detector = cv2.FaceDetectorYN.create(
            self.detector_path, "", (320, 320), 0.6, 0.3, 5000
        )
        self.recognizer = cv2.FaceRecognizerSF.create(self.recognizer_path, "")

    def load_image_with_exif(self, path: str) -> Optional[np.ndarray]:
        """Pillow를 통해 EXIF 방향 정보를 자동 보정한 뒤 OpenCV BGR 배열로 반환
        - 스마트폰으로 촬영된 사진의 회전 메타데이터 자동 보정
        - 한글 경로 및 다양한 이미지 포맷 지원
        """
        try:
            with Image.open(path) as pil_img:
                pil_img = ImageOps.exif_transpose(pil_img)
                if pil_img.mode != "RGB":
                    pil_img = pil_img.convert("RGB")
                rgb_arr = np.array(pil_img)
                bgr_img = cv2.cvtColor(rgb_arr, cv2.COLOR_RGB2BGR)
                return bgr_img
        except Exception:
            try:
                with open(path, "rb") as f:
                    bytes_data = bytearray(f.read())
                arr = np.asarray(bytes_data, dtype=np.uint8)
                return cv2.imdecode(arr, cv2.IMREAD_COLOR)
            except Exception:
                return None

    def detect_and_extract_features(
        self, img: np.ndarray, max_side: int = 1280
    ) -> List[Tuple[np.ndarray, np.ndarray]]:
        """이미지 내 모든 얼굴을 검출하고 128차원 정규화 특징 벡터 추출"""
        if img is None:
            return []

        self.ensure_models_loaded()

        h, w = img.shape[:2]
        scale = 1.0
        if max(h, w) > max_side:
            scale = max_side / float(max(h, w))
            new_w, new_h = max(32, int(w * scale)), max(32, int(h * scale))
            resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
        else:
            resized = img
            new_w, new_h = w, h

        self.detector.setInputSize((new_w, new_h))
        _, faces = self.detector.detect(resized)

        if faces is None or len(faces) == 0:
            return []

        results = []
        for face in faces:
            # 극소형 노이즈 얼굴 필터링 (가로/세로 18px 미만 또는 면적 324 미만 노이즈 배제)
            fw, fh = face[2], face[3]
            if fw < 18 or fh < 18 or (fw * fh) < 324:
                continue

            if scale != 1.0:
                face_orig = face.copy()
                face_orig[:-1] /= scale
            else:
                face_orig = face

            try:
                aligned = self.recognizer.alignCrop(img, face_orig)
                feature = self.recognizer.feature(aligned)
                results.append((face_orig, feature))
            except Exception:
                continue

        return results

    @staticmethod
    def scan_student_folders(profile_dir: str) -> List[Dict[str, Any]]:
        """초경량 메타데이터 전용 스캔: 모델 로딩이나 특징 추출 없이 폴더 구조만 즉각 파악
        - UI에 0.01초 내로 학생 목록과 사진 매수를 띄워 프리즈 현상 원천 방지
        """
        if not profile_dir or not os.path.exists(profile_dir):
            return []

        valid_exts = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
        entries = sorted(os.listdir(profile_dir))
        result = []

        for entry in entries:
            student_path = os.path.join(profile_dir, entry)
            if not os.path.isdir(student_path):
                continue

            student_name = sanitize_filename(entry)
            img_files = [
                f for f in sorted(os.listdir(student_path))
                if os.path.splitext(f.lower())[1] in valid_exts
            ]

            first_img_path = os.path.join(student_path, img_files[0]) if img_files else None

            result.append({
                "name": student_name,
                "folder_path": student_path,
                "count": len(img_files),
                "first_img_path": first_img_path,
            })

        return result

    @staticmethod
    def create_student_folder(profile_dir: str, student_name: str) -> str:
        """새 학생 폴더 생성"""
        clean_name = sanitize_filename(student_name)
        if not clean_name:
            raise ValueError("학생 이름을 입력해주세요.")
        target_path = safe_join(profile_dir, clean_name)
        os.makedirs(target_path, exist_ok=True)
        return clean_name

    @staticmethod
    def delete_student_folder(profile_dir: str, student_name: str) -> bool:
        """학생 폴더 삭제"""
        clean_name = sanitize_filename(student_name)
        target_path = safe_join(profile_dir, clean_name)
        if os.path.exists(target_path):
            shutil.rmtree(target_path, ignore_errors=True)
            return True
        return False

    @staticmethod
    def rename_student_folder(profile_dir: str, old_name: str, new_name: str) -> str:
        """학생 폴더명 변경 (오타 수정 및 학번/이름 변경)"""
        clean_old = sanitize_filename(old_name)
        clean_new = sanitize_filename(new_name)
        if not clean_new:
            raise ValueError("새 학생 이름을 입력해주세요.")
        old_path = safe_join(profile_dir, clean_old)
        new_path = safe_join(profile_dir, clean_new)
        if not os.path.exists(old_path):
            raise FileNotFoundError(f"기존 학생 폴더를 찾을 수 없습니다: {old_name}")
        if os.path.exists(new_path) and old_path != new_path:
            raise FileExistsError(f"이미 동일한 이름의 학생 폴더가 존재합니다: {new_name}")
        os.rename(old_path, new_path)
        return clean_new

    @staticmethod
    def list_student_photos(profile_dir: str, student_name: str) -> List[Dict[str, Any]]:
        """특정 학생의 기준 사진 상세 목록 조회"""
        clean_name = sanitize_filename(student_name)
        student_path = safe_join(profile_dir, clean_name)
        if not os.path.exists(student_path):
            return []
        valid_exts = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
        files = sorted(os.listdir(student_path))
        results = []
        for f in files:
            ext = os.path.splitext(f.lower())[1]
            if ext in valid_exts:
                full_path = os.path.join(student_path, f)
                size_kb = os.path.getsize(full_path) // 1024
                results.append({
                    "filename": f,
                    "path": full_path,
                    "size_kb": size_kb
                })
        return results

    @staticmethod
    def add_photos_to_student(profile_dir: str, student_name: str, source_paths: List[str]) -> int:
        """선택된 사진 파일들을 특정 학생 기준 사진으로 복사 추가"""
        clean_name = sanitize_filename(student_name)
        student_path = safe_join(profile_dir, clean_name)
        os.makedirs(student_path, exist_ok=True)
        added_count = 0
        for src in source_paths:
            if os.path.exists(src) and os.path.isfile(src):
                filename = os.path.basename(src)
                dest = get_unique_destination_path(student_path, filename)
                shutil.copy2(src, dest)
                added_count += 1
        return added_count

    @staticmethod
    def delete_student_photo_file(profile_dir: str, student_name: str, filename: str) -> bool:
        """학생 폴더 내 특정 기준 사진 삭제"""
        clean_name = sanitize_filename(student_name)
        clean_filename = os.path.basename(filename)
        target_file = safe_join(profile_dir, clean_name, clean_filename)
        if os.path.exists(target_file) and os.path.isfile(target_file):
            os.remove(target_file)
            return True
        return False

    @staticmethod
    def move_student_photo_file(profile_dir: str, from_student: str, to_student: str, filename: str) -> bool:
        """특정 학생의 기준 사진을 다른 학생 폴더로 이동"""
        clean_from = sanitize_filename(from_student)
        clean_to = sanitize_filename(to_student)
        clean_file = os.path.basename(filename)
        src_file = safe_join(profile_dir, clean_from, clean_file)
        dest_dir = safe_join(profile_dir, clean_to)
        if not os.path.exists(src_file):
            return False
        os.makedirs(dest_dir, exist_ok=True)
        dest_file = get_unique_destination_path(dest_dir, clean_file)
        shutil.move(src_file, dest_file)
        return True

    def load_students(
        self, profile_dir: str, log_cb: Optional[Callable[[str], None]] = None
    ) -> Dict[str, StudentProfile]:
        """학생 기준 사진 폴더를 스캔하여 각 학생별 특징 벡터 구축 (분류 작업 시작 시 백그라운드 호출)"""
        self.ensure_models_loaded()
        students: Dict[str, StudentProfile] = {}
        if not os.path.exists(profile_dir):
            return students

        valid_exts = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
        entries = sorted(os.listdir(profile_dir))

        for entry in entries:
            student_path = os.path.join(profile_dir, entry)
            if not os.path.isdir(student_path):
                continue

            student_name = sanitize_filename(entry)
            profile = StudentProfile(name=student_name, folder_path=student_path)

            img_files = [
                f for f in sorted(os.listdir(student_path))
                if os.path.splitext(f.lower())[1] in valid_exts
            ]
            profile.image_count = len(img_files)

            for img_file in img_files:
                full_path = os.path.join(student_path, img_file)
                img = self.load_image_with_exif(full_path)
                if img is None:
                    continue

                detections = self.detect_and_extract_features(img)
                if detections:
                    best_detection = max(
                        detections, key=lambda d: d[0][2] * d[0][3]
                    )
                    profile.features.append(best_detection[1])

            if profile.features:
                students[student_name] = profile
                if log_cb:
                    log_cb(f"학생 등록 완료: {student_name} (얼굴 특징 {len(profile.features)}개 확보)")
            else:
                if log_cb:
                    log_cb(f"⚠️ 얼굴 감지 필요: {student_name} 학생 폴더에 선명한 얼굴 사진을 넣어주세요.")

        return students

    def sort_photos(
        self,
        target_dir: str,
        output_dir: str,
        students: Dict[str, StudentProfile],
        threshold: float = 0.40,
        copy_multi_person: bool = True,
        keep_original: bool = True,
        progress_cb: Optional[Callable[[int, int, str, SortStats], None]] = None,
        log_cb: Optional[Callable[[str], None]] = None,
    ) -> SortStats:
        """대상 사진들을 분석하여 일치하는 학생 폴더로 안전 복사/이동"""
        self.is_cancelled = False
        stats = SortStats()
        start_time = time.time()

        if not os.path.exists(target_dir):
            if log_cb:
                log_cb(f"❌ 대상 사진 폴더가 존재하지 않습니다: {target_dir}")
            return stats

        valid_exts = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
        files = [
            f for f in sorted(os.listdir(target_dir))
            if os.path.splitext(f.lower())[1] in valid_exts
        ]

        total_files = len(files)
        stats.total_scanned = total_files

        for s_name in students.keys():
            stats.student_matches[s_name] = 0

        unclassified_dir = safe_join(output_dir, "_미분류")
        os.makedirs(unclassified_dir, exist_ok=True)

        for idx, filename in enumerate(files, 1):
            if self.is_cancelled:
                if log_cb:
                    log_cb("⏹️ 사용자에 의해 분류 작업이 즉시 중단되었습니다.")
                break

            filepath = os.path.join(target_dir, filename)
            img = self.load_image_with_exif(filepath)

            if img is None:
                stats.unclassified_count += 1
                dest_path = get_unique_destination_path(unclassified_dir, filename)
                shutil.copy2(filepath, dest_path)
                continue

            detections = self.detect_and_extract_features(img)
            matched_students: Dict[str, float] = {}

            if detections:
                for _, feat in detections:
                    best_match_name = None
                    best_score = -1.0

                    for s_name, profile in students.items():
                        for ref_feat in profile.features:
                            score = self.recognizer.match(
                                ref_feat, feat, cv2.FaceRecognizerSF_FR_COSINE
                            )
                            if score > best_score:
                                best_score = score
                                if score >= threshold:
                                    best_match_name = s_name

                    if best_match_name:
                        if best_match_name not in matched_students or best_score > matched_students[best_match_name]:
                            matched_students[best_match_name] = best_score

            if matched_students:
                stats.classified_count += 1
                if len(matched_students) > 1:
                    stats.multi_person_count += 1

                sorted_matches = sorted(matched_students.items(), key=lambda x: x[1], reverse=True)
                targets_to_copy = [m[0] for m in sorted_matches] if copy_multi_person else [sorted_matches[0][0]]
                match_logs = [f"{name}({score:.2f})" for name, score in sorted_matches]

                for name in targets_to_copy:
                    s_dir = safe_join(output_dir, name)
                    os.makedirs(s_dir, exist_ok=True)
                    dest_file = get_unique_destination_path(s_dir, filename)

                    if not keep_original and len(targets_to_copy) == 1:
                        shutil.move(filepath, dest_file)
                    else:
                        shutil.copy2(filepath, dest_file)

                    stats.student_matches[name] = stats.student_matches.get(name, 0) + 1

                if log_cb:
                    log_cb(f"[{idx}/{total_files}] 매칭: {filename} ➔ {', '.join(match_logs)}")
            else:
                stats.unclassified_count += 1
                dest_path = get_unique_destination_path(unclassified_dir, filename)
                shutil.copy2(filepath, dest_path)
                if log_cb:
                    log_cb(f"[{idx}/{total_files}] 미분류: {filename} ➔ _미분류 폴더 보관")

            elapsed = max(0.001, time.time() - start_time)
            stats.items_per_second = round(idx / elapsed, 1)

            if progress_cb:
                progress_cb(idx, total_files, filename, stats)

        stats.elapsed_seconds = time.time() - start_time
        return stats
