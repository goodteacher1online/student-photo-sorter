// ==========================================================================
// NOTHING DESIGN SYSTEM — 학생 사진 자동 분류기 클라이언트 스크립트
// - 학생 명단 직접 관리 (등록 / 삭제 / 이름변경 / 사진추가 / 사진이동)
// - 비차단(Non-blocking) 실시간 폴링 아키텍처
// - 상태 메터 중복 텍스트 완전 정리
// ==========================================================================

document.addEventListener('DOMContentLoaded', () => {
  // --- DOM 요소 참조 ---
  const btnThemeToggle = document.getElementById('btnThemeToggle');
  const btnCreateSample = document.getElementById('btnCreateSample');
  const btnSelectProfile = document.getElementById('btnSelectProfile');
  const btnSelectTarget = document.getElementById('btnSelectTarget');
  const btnSelectOutput = document.getElementById('btnSelectOutput');
  const btnReloadStudents = document.getElementById('btnReloadStudents');
  const btnAddStudent = document.getElementById('btnAddStudent');
  const btnStartSort = document.getElementById('btnStartSort');
  const btnCancelSort = document.getElementById('btnCancelSort');
  const btnOpenOutput = document.getElementById('btnOpenOutput');
  const btnOpenOutputFolder = document.getElementById('btnOpenOutputFolder');

  const dropZoneProfile = document.getElementById('dropZoneProfile');
  const dropZoneTarget = document.getElementById('dropZoneTarget');
  const dropZoneOutput = document.getElementById('dropZoneOutput');

  const profileDirPath = document.getElementById('profileDirPath');
  const targetDirPath = document.getElementById('targetDirPath');
  const outputDirPath = document.getElementById('outputDirPath');

  const thresholdSlider = document.getElementById('thresholdSlider');
  const thresholdValBadge = document.getElementById('thresholdValBadge');
  const checkMultiPerson = document.getElementById('checkMultiPerson');
  const checkKeepOriginal = document.getElementById('checkKeepOriginal');

  const kpiTotalScanned = document.getElementById('kpiTotalScanned');
  const kpiClassified = document.getElementById('kpiClassified');
  const kpiMultiPerson = document.getElementById('kpiMultiPerson');
  const kpiUnclassified = document.getElementById('kpiUnclassified');

  const studentsTotalBadge = document.getElementById('studentsTotalBadge');
  const studentsCardsContainer = document.getElementById('studentsCardsContainer');

  const meterStatusText = document.getElementById('meterStatusText');
  const meterSpeedBadge = document.getElementById('meterSpeedBadge');
  const meterPercent = document.getElementById('meterPercent');
  const meterProgressFill = document.getElementById('meterProgressFill');
  const currentPhotoLabel = document.getElementById('currentPhotoLabel');
  const terminalBody = document.getElementById('terminalBody');

  const resultsShelf = document.getElementById('resultsShelf');
  const resultsGrid = document.getElementById('resultsGrid');

  // 모달 참조
  const studentDetailModal = document.getElementById('studentDetailModal');
  const modalStudentTitle = document.getElementById('modalStudentTitle');
  const modalStudentNameInput = document.getElementById('modalStudentNameInput');
  const btnRenameStudent = document.getElementById('btnRenameStudent');
  const modalPhotoCountBadge = document.getElementById('modalPhotoCountBadge');
  const btnAddStudentPhotos = document.getElementById('btnAddStudentPhotos');
  const btnOpenStudentFolder = document.getElementById('btnOpenStudentFolder');
  const modalPhotoGrid = document.getElementById('modalPhotoGrid');
  const btnDeleteStudent = document.getElementById('btnDeleteStudent');
  const btnModalClose = document.getElementById('btnModalClose');
  const btnModalCloseBottom = document.getElementById('btnModalCloseBottom');

  const addStudentModal = document.getElementById('addStudentModal');
  const newStudentNameInput = document.getElementById('newStudentNameInput');
  const btnConfirmAddStudent = document.getElementById('btnConfirmAddStudent');
  const btnCancelAddStudent = document.getElementById('btnCancelAddStudent');
  const btnAddModalClose = document.getElementById('btnAddModalClose');

  let isSorting = false;
  let pollingTimer = null;
  let currentActiveStudent = null;
  let cachedStudentsList = [];

  // --- 시간 포맷 헬퍼 ---
  function getTimeStr() {
    const now = new Date();
    return now.toTimeString().split(' ')[0];
  }

  // --- 실시간 터미널 로그 출력 ---
  function addLog(msg, type = 'normal') {
    const line = document.createElement('div');
    line.className = 'terminal-line';

    let msgClass = 'terminal-msg';
    if (type === 'accent' || msg.includes('매칭')) msgClass += ' accent';
    if (type === 'success' || msg.includes('완료') || msg.includes('성공')) msgClass += ' success';

    line.innerHTML = `
      <span class="terminal-time">[${getTimeStr()}]</span>
      <span class="${msgClass}">${msg}</span>
    `;
    terminalBody.appendChild(line);
    terminalBody.scrollTop = terminalBody.scrollHeight;
  }

  // --- 테마 전환 ---
  btnThemeToggle.addEventListener('click', () => {
    document.body.classList.toggle('dark-theme');
    const isDark = document.body.classList.contains('dark-theme');
    btnThemeToggle.textContent = isDark ? '☼' : '☾';
  });

  // --- 정밀도 슬라이더 실시간 바인딩 ---
  thresholdSlider.addEventListener('input', (e) => {
    thresholdValBadge.textContent = parseFloat(e.target.value).toFixed(2);
  });

  // --- pywebview API 안전 호출 래퍼 ---
  async function callApi(fnName, ...args) {
    if (window.pywebview && window.pywebview.api && typeof window.pywebview.api[fnName] === 'function') {
      try {
        return await window.pywebview.api[fnName](...args);
      } catch (err) {
        console.error(`API Call [${fnName}] Error:`, err);
        addLog(`⚠️ [${fnName}] 오류: ${err}`, 'accent');
        return null;
      }
    } else {
      console.warn(`pywebview.api.${fnName} 아직 준비되지 않음`);
      return null;
    }
  }

  // --- 드래그 앤 드롭 폴더 바인딩 ---
  function setupDragAndDrop(dropZone, inputEl, onFolderSet) {
    ['dragenter', 'dragover'].forEach(eventName => {
      dropZone.addEventListener(eventName, (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropZone.classList.add('drag-active');
      }, false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
      dropZone.addEventListener(eventName, (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropZone.classList.remove('drag-active');
      }, false);
    });

    dropZone.addEventListener('drop', (e) => {
      const files = e.dataTransfer.files;
      if (files && files.length > 0) {
        const path = files[0].path;
        if (path) {
          inputEl.value = path;
          addLog(`폴더 드래그 앤 드롭 지정: ${path}`);
          if (onFolderSet) onFolderSet(path);
        }
      }
    });
  }

  setupDragAndDrop(dropZoneProfile, profileDirPath, (path) => reloadStudentsList(path));
  setupDragAndDrop(dropZoneTarget, targetDirPath, (path) => {
    if (!outputDirPath.value) outputDirPath.value = path + '\\분류결과';
  });
  setupDragAndDrop(dropZoneOutput, outputDirPath);

  // --- 학생 명단 렌더링 ---
  function renderStudents(studentsList) {
    cachedStudentsList = studentsList || [];
    if (!studentsList || studentsList.length === 0) {
      studentsTotalBadge.textContent = '0명 등록';
      studentsCardsContainer.innerHTML = `
        <div class="empty-students-notice">
          등록된 학생이 없습니다. [+ 학생 등록] 버튼을 눌러 학생을 추가하거나, 학생 기준 사진 폴더를 지정해주세요.
        </div>
      `;
      return;
    }

    studentsTotalBadge.textContent = `${studentsList.length}명 등록`;
    studentsCardsContainer.innerHTML = '';

    studentsList.forEach(s => {
      const chip = document.createElement('div');
      chip.className = 'student-chip';
      chip.title = `${s.name} 학생 상세 관리 (클릭 시 사진 추가, 삭제, 이름변경)`;

      const avatarContent = s.preview_thumb
        ? `<img class="student-avatar" src="${s.preview_thumb}" alt="${s.name}">`
        : `<div class="student-avatar">${s.name.charAt(0)}</div>`;

      chip.innerHTML = `
        ${avatarContent}
        <span class="student-chip-name">${s.name}</span>
        <span class="student-chip-count">${s.count}장 기준사진</span>
      `;

      // 클릭 시 학생 상세 관리 모달 열기
      chip.addEventListener('click', () => {
        openStudentDetailModal(s.name);
      });

      studentsCardsContainer.appendChild(chip);
    });
  }

  // --- 학생 상세 관리 모달 열기 ---
  async function openStudentDetailModal(studentName) {
    const profileDir = profileDirPath.value;
    if (!profileDir) {
      alert('학생 기준 사진 폴더가 설정되지 않았습니다.');
      return;
    }

    currentActiveStudent = studentName;
    modalStudentTitle.textContent = `${studentName} 학생 관리`;
    modalStudentNameInput.value = studentName;
    modalPhotoGrid.innerHTML = '<div style="padding: 20px; color: var(--text-tertiary); font-size: 14px;">사진 목록을 불러오는 중...</div>';
    studentDetailModal.style.display = 'flex';

    await refreshStudentDetail(studentName);
  }

  // --- 학생 상세 사진 새로고침 ---
  async function refreshStudentDetail(studentName) {
    const profileDir = profileDirPath.value;
    const res = await callApi('get_student_detail', profileDir, studentName);

    if (!res || !res.success) {
      modalPhotoGrid.innerHTML = '<div style="padding: 20px; color: #EF4444; font-size: 14px;">사진 목록을 불러오지 못했습니다.</div>';
      return;
    }

    const photos = res.photos || [];
    modalPhotoCountBadge.textContent = `${photos.length}장 등록`;

    if (photos.length === 0) {
      modalPhotoGrid.innerHTML = `
        <div style="grid-column: 1 / -1; padding: 30px 10px; text-align: center; color: var(--text-tertiary); font-size: 14px;">
          등록된 기준 사진이 없습니다.<br>
          <strong style="color: var(--accent);">[+ 기준 사진 추가]</strong> 버튼을 눌러 사진을 등록해주세요.
        </div>
      `;
      return;
    }

    modalPhotoGrid.innerHTML = '';
    photos.forEach(p => {
      const card = document.createElement('div');
      card.className = 'photo-item-card';

      const imgHtml = p.thumb
        ? `<img src="${p.thumb}" alt="${p.filename}">`
        : `<div style="display:flex;align-items:center;justify-content:center;height:100%;font-size:12px;color:var(--text-tertiary);">${p.filename}</div>`;

      card.innerHTML = `
        ${imgHtml}
        <div class="photo-actions-overlay">
          <button class="photo-action-btn btn-move-photo" title="다른 학생 폴더로 이동">이동</button>
          <button class="photo-action-btn btn-del-photo" title="이 사진 삭제" style="color: #F87171;">삭제</button>
        </div>
      `;

      // 사진 삭제 이벤트
      card.querySelector('.btn-del-photo').addEventListener('click', async (e) => {
        e.stopPropagation();
        if (confirm(`'${p.filename}' 기준 사진을 정말 삭제하시겠습니까?`)) {
          const delRes = await callApi('delete_student_photo', profileDir, currentActiveStudent, p.filename);
          if (delRes && delRes.success) {
            addLog(`🗑️ ${currentActiveStudent} 학생의 '${p.filename}' 사진 삭제 완료`);
            await refreshStudentDetail(currentActiveStudent);
            await reloadStudentsList(profileDir);
          } else {
            alert(delRes ? delRes.error : '삭제 실패');
          }
        }
      });

      // 사진 이동 이벤트
      card.querySelector('.btn-move-photo').addEventListener('click', async (e) => {
        e.stopPropagation();
        const otherStudents = cachedStudentsList.filter(s => s.name !== currentActiveStudent).map(s => s.name);
        if (otherStudents.length === 0) {
          alert('이동할 수 있는 다른 학생이 없습니다. 먼저 다른 학생을 등록해주세요.');
          return;
        }

        const targetStudent = prompt(
          `'${p.filename}' 사진을 이동할 학생 이름을 정확히 입력하세요:\n(등록된 학생: ${otherStudents.join(', ')})`,
          otherStudents[0]
        );

        if (targetStudent && targetStudent.trim()) {
          const moveRes = await callApi('move_student_photo', profileDir, currentActiveStudent, targetStudent.trim(), p.filename);
          if (moveRes && moveRes.success) {
            addLog(`📦 사진 이동: ${currentActiveStudent} ➔ ${targetStudent.trim()} ('${p.filename}')`);
            await refreshStudentDetail(currentActiveStudent);
            await reloadStudentsList(profileDir);
          } else {
            alert(moveRes ? moveRes.error : '사진 이동 실패');
          }
        }
      });

      modalPhotoGrid.appendChild(card);
    });
  }

  // --- 학생 이름 변경 ---
  btnRenameStudent.addEventListener('click', async () => {
    const profileDir = profileDirPath.value;
    const newName = modalStudentNameInput.value.trim();
    if (!newName) {
      alert('학생 이름을 입력해주세요.');
      return;
    }
    if (newName === currentActiveStudent) {
      return;
    }

    const res = await callApi('rename_student', profileDir, currentActiveStudent, newName);
    if (res && res.success) {
      addLog(`✏️ 학생 이름 변경: ${currentActiveStudent} ➔ ${res.name}`, 'success');
      currentActiveStudent = res.name;
      modalStudentTitle.textContent = `${res.name} 학생 관리`;
      await reloadStudentsList(profileDir);
    } else {
      alert(res ? res.error : '이름 변경에 실패했습니다.');
    }
  });

  // --- 학생 기준 사진 추가 ---
  btnAddStudentPhotos.addEventListener('click', async () => {
    const profileDir = profileDirPath.value;
    if (!profileDir || !currentActiveStudent) return;

    const files = await callApi('select_images', `${currentActiveStudent} 학생 기준 사진 추가`);
    if (files && files.length > 0) {
      const res = await callApi('add_student_photos', profileDir, currentActiveStudent, files);
      if (res && res.success) {
        addLog(`📸 ${currentActiveStudent} 학생에게 기준 사진 ${res.added_count}장 추가 완료`, 'success');
        await refreshStudentDetail(currentActiveStudent);
        await reloadStudentsList(profileDir);
      } else {
        alert(res ? res.error : '사진 추가에 실패했습니다.');
      }
    }
  });

  // --- 해당 학생 폴더 열기 ---
  btnOpenStudentFolder.addEventListener('click', async () => {
    const profileDir = profileDirPath.value;
    if (profileDir && currentActiveStudent) {
      await callApi('open_student_folder', profileDir, currentActiveStudent);
    }
  });

  // --- 학생 삭제 ---
  btnDeleteStudent.addEventListener('click', async () => {
    const profileDir = profileDirPath.value;
    if (!profileDir || !currentActiveStudent) return;

    if (confirm(`'${currentActiveStudent}' 학생 및 등록된 모든 기준 사진을 완전히 삭제하시겠습니까?`)) {
      const res = await callApi('delete_student', profileDir, currentActiveStudent);
      if (res && res.success) {
        addLog(`🗑️ ${currentActiveStudent} 학생 폴더 및 명단 삭제 완료`);
        studentDetailModal.style.display = 'none';
        currentActiveStudent = null;
        await reloadStudentsList(profileDir);
      } else {
        alert(res ? res.error : '학생 삭제 실패');
      }
    }
  });

  // 모달 닫기 이벤트
  const closeModal = () => { studentDetailModal.style.display = 'none'; currentActiveStudent = null; };
  btnModalClose.addEventListener('click', closeModal);
  btnModalCloseBottom.addEventListener('click', closeModal);

  // --- 새 학생 등록 모달 열기 ---
  btnAddStudent.addEventListener('click', () => {
    const profileDir = profileDirPath.value;
    if (!profileDir) {
      alert('먼저 [1. 학생 기준 사진 폴더]를 선택하거나 설정해주세요.');
      return;
    }
    newStudentNameInput.value = '';
    addStudentModal.style.display = 'flex';
    newStudentNameInput.focus();
  });

  const closeAddModal = () => { addStudentModal.style.display = 'none'; };
  btnAddModalClose.addEventListener('click', closeAddModal);
  btnCancelAddStudent.addEventListener('click', closeAddModal);

  // 새 학생 등록 확인
  btnConfirmAddStudent.addEventListener('click', async () => {
    const profileDir = profileDirPath.value;
    const name = newStudentNameInput.value.trim();
    if (!name) {
      alert('등록할 학생 이름을 입력해주세요.');
      return;
    }

    const res = await callApi('add_student', profileDir, name);
    if (res && res.success) {
      addLog(`✨ 새 학생 등록 완료: ${res.name}`, 'success');
      closeAddModal();
      await reloadStudentsList(profileDir);

      // 등록 직후 바로 기준 사진을 추가할 것인지 묻기
      if (confirm(`'${res.name}' 학생이 등록되었습니다.\n지금 바로 기준 사진을 등록하시겠습니까?`)) {
        openStudentDetailModal(res.name);
      }
    } else {
      alert(res ? res.error : '학생 등록에 실패했습니다.');
    }
  });

  // --- 폴더 선택 버튼 이벤트 ---
  btnSelectProfile.addEventListener('click', async () => {
    const selected = await callApi('select_folder', '학생 기준 사진 폴더 선택');
    if (selected) {
      profileDirPath.value = selected;
      addLog(`학생 기준 폴더 지정: ${selected}`);
      await reloadStudentsList(selected);
    }
  });

  btnSelectTarget.addEventListener('click', async () => {
    const selected = await callApi('select_folder', '분류 대상 사진 폴더 선택');
    if (selected) {
      targetDirPath.value = selected;
      addLog(`분류 대상 사진 폴더 지정: ${selected}`);
      if (!outputDirPath.value) {
        outputDirPath.value = selected + '\\분류결과';
      }
    }
  });

  btnSelectOutput.addEventListener('click', async () => {
    const selected = await callApi('select_folder', '분류 결과 저장 폴더 선택');
    if (selected) {
      outputDirPath.value = selected;
      addLog(`결과 저장 폴더 지정: ${selected}`);
    }
  });

  // --- 학생 기준 목록 새로고침 ---
  let isLoadingStudents = false;
  async function reloadStudentsList(folder) {
    if (isLoadingStudents) return;
    const target = folder || profileDirPath.value;
    if (!target) return;
    isLoadingStudents = true;
    try {
      addLog(`학생 기준 폴더 스캔: ${target}`);
      const res = await callApi('scan_student_profiles', target);
      if (res) {
        if (res.logs && Array.isArray(res.logs)) {
          res.logs.forEach(l => addLog(l));
        }
        if (res.students) {
          renderStudents(res.students);
        }
      }
    } finally {
      isLoadingStudents = false;
    }
  }

  btnReloadStudents.addEventListener('click', () => {
    reloadStudentsList();
  });

  // --- 비차단 실시간 폴링 루프 (대기 텍스트 중복 및 겹침 해결) ---
  function startPolling() {
    if (pollingTimer) clearInterval(pollingTimer);

    pollingTimer = setInterval(async () => {
      const resp = await callApi('get_sorting_state');
      if (!resp) return;

      const { state, logs } = resp;

      if (logs && logs.length > 0) {
        logs.forEach(l => addLog(l));
      }

      if (!state) return;

      const pct = state.total > 0 ? Math.round((state.current / state.total) * 100) : 0;
      meterPercent.textContent = `${pct}%`;
      meterProgressFill.style.width = `${pct}%`;

      if (state.filename) {
        currentPhotoLabel.textContent = `[${state.current}/${state.total}] 분석 중: ${state.filename}`;
      }

      if (state.items_per_second > 0) {
        meterSpeedBadge.textContent = `// 속도: ${state.items_per_second}장/초`;
      }

      if (state.stats) {
        kpiTotalScanned.textContent = state.stats.total_scanned || state.total;
        kpiClassified.textContent = state.stats.classified_count || 0;
        kpiMultiPerson.textContent = state.stats.multi_person_count || 0;
        kpiUnclassified.textContent = state.stats.unclassified_count || 0;
      }

      // 작업 완료 시 처리 ('// 대기 중' 중복 텍스트 완전 제거)
      if (state.status === 'completed') {
        clearInterval(pollingTimer);
        pollingTimer = null;
        isSorting = false;
        btnStartSort.style.display = 'inline-flex';
        btnCancelSort.style.display = 'none';
        meterStatusText.textContent = '분류 완료';
        meterPercent.textContent = '100%';
        meterProgressFill.style.width = '100%';
        currentPhotoLabel.textContent = `전체 작업 완료 (소요 시간: ${state.stats ? state.stats.elapsed_seconds : 0}초)`;
        if (state.stats) {
          renderResultsGrid(state.stats.student_matches, state.stats.unclassified_count);
        }
        addLog(`🎉 사진 분류가 성공적으로 완료되었습니다!`, 'success');
      } else if (state.status === 'cancelled') {
        clearInterval(pollingTimer);
        pollingTimer = null;
        isSorting = false;
        btnStartSort.style.display = 'inline-flex';
        btnCancelSort.style.display = 'none';
        meterStatusText.textContent = '작업 중단됨';
        meterSpeedBadge.textContent = '';
        currentPhotoLabel.textContent = '사용자에 의해 작업이 중단되었습니다.';
        addLog('⏹️ 사진 분류 작업이 중단되었습니다.');
      } else if (state.status === 'error') {
        clearInterval(pollingTimer);
        pollingTimer = null;
        isSorting = false;
        btnStartSort.style.display = 'inline-flex';
        btnCancelSort.style.display = 'none';
        meterStatusText.textContent = '오류 발생';
        currentPhotoLabel.textContent = '분류 중 오류가 발생했습니다. 로그를 확인하세요.';
      }
    }, 120);
  }

  // --- 사진 분류 시작 ---
  btnStartSort.addEventListener('click', async () => {
    if (!profileDirPath.value) {
      alert('1. 학생 기준 사진 폴더를 지정해주세요.');
      return;
    }
    if (!targetDirPath.value) {
      alert('2. 분류 대상 사진 폴더를 지정해주세요.');
      return;
    }
    if (!outputDirPath.value) {
      outputDirPath.value = targetDirPath.value + '\\분류결과';
    }

    isSorting = true;
    btnStartSort.style.display = 'none';
    btnCancelSort.style.display = 'inline-flex';
    resultsShelf.classList.remove('active');
    resultsGrid.innerHTML = '';

    meterStatusText.textContent = '분류 진행 중';
    meterSpeedBadge.textContent = '';
    meterPercent.textContent = '0%';
    meterProgressFill.style.width = '0%';
    currentPhotoLabel.textContent = 'AI 얼굴 모델 초기화 및 분류 준비 중...';

    addLog('🚀 사진 분류 프로세스 시작 (온디바이스 비차단 모드)');

    const params = {
      profile_dir: profileDirPath.value,
      target_dir: targetDirPath.value,
      output_dir: outputDirPath.value,
      threshold: parseFloat(thresholdSlider.value),
      copy_multi: checkMultiPerson.checked,
      keep_original: checkKeepOriginal.checked,
    };

    await callApi('start_sorting', params);
    startPolling();
  });

  // --- 작업 취소 ---
  btnCancelSort.addEventListener('click', async () => {
    addLog('작업 중단 요청 중...');
    await callApi('cancel_sorting');
  });

  // --- 결과 카드 그리드 렌더링 ---
  function renderResultsGrid(studentMatches, unclassifiedCount) {
    resultsGrid.innerHTML = '';
    resultsShelf.classList.add('active');

    if (studentMatches) {
      Object.entries(studentMatches).forEach(([name, count]) => {
        const card = document.createElement('div');
        card.className = 'result-card';
        card.innerHTML = `
          <div class="result-card-header">
            <span class="result-card-name">${name}</span>
            <span class="result-card-count">${count}장</span>
          </div>
          <button class="result-card-btn" data-subfolder="${name}">폴더 열기</button>
        `;
        card.querySelector('.result-card-btn').addEventListener('click', () => {
          const subPath = outputDirPath.value ? outputDirPath.value + '\\' + name : '';
          if (subPath) callApi('open_folder', subPath);
        });
        resultsGrid.appendChild(card);
      });
    }

    if (unclassifiedCount > 0) {
      const unclassCard = document.createElement('div');
      unclassCard.className = 'result-card';
      unclassCard.innerHTML = `
        <div class="result-card-header">
          <span class="result-card-name" style="color: var(--accent);">_미분류</span>
          <span class="result-card-count">${unclassifiedCount}장</span>
        </div>
        <button class="result-card-btn" data-subfolder="_미분류">미분류 확인</button>
      `;
      unclassCard.querySelector('.result-card-btn').addEventListener('click', () => {
        const subPath = outputDirPath.value ? outputDirPath.value + '\\_미분류' : '';
        if (subPath) callApi('open_folder', subPath);
      });
      resultsGrid.appendChild(unclassCard);
    }
  }

  const handleOpenOutput = async () => {
    const out = outputDirPath.value;
    if (out) {
      await callApi('open_folder', out);
    } else {
      alert('결과 저장 폴더가 아직 설정되지 않았습니다.');
    }
  };

  btnOpenOutput.addEventListener('click', handleOpenOutput);
  if (btnOpenOutputFolder) btnOpenOutputFolder.addEventListener('click', handleOpenOutput);

  // --- 예제 샘플 생성 ---
  btnCreateSample.addEventListener('click', async () => {
    addLog('테스트용 샘플 디렉토리 생성 중...');
    const result = await callApi('create_sample_dataset');
    if (result) {
      profileDirPath.value = result.profile_dir;
      targetDirPath.value = result.target_dir;
      outputDirPath.value = result.output_dir;
      await reloadStudentsList(result.profile_dir);
      addLog(`✅ 테스트 샘플 폴더 생성 완료! ${result.profile_dir}`, 'success');
    }
  });

  // --- 앱 시작 초기화 ---
  window.addEventListener('pywebviewready', () => {
    setTimeout(async () => {
      addLog('온디바이스 Python 브리지와 성공적으로 연결되었습니다.');
      const sysInfo = await callApi('get_system_info');
      if (sysInfo) {
        addLog(`엔진 사양: OpenCV ${sysInfo.opencv_version} (YuNet 고속검출 + SFace 얼굴인식)`);
        if (sysInfo.default_dirs) {
          if (sysInfo.default_dirs.profile_dir) profileDirPath.value = sysInfo.default_dirs.profile_dir;
          if (sysInfo.default_dirs.target_dir) targetDirPath.value = sysInfo.default_dirs.target_dir;
          if (sysInfo.default_dirs.output_dir) outputDirPath.value = sysInfo.default_dirs.output_dir;
          if (profileDirPath.value) {
            reloadStudentsList(profileDirPath.value);
          }
        }
      }
    }, 50);
  });
});
