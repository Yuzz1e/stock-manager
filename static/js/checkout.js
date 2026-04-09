document.addEventListener('DOMContentLoaded', () => {
  const cameraBtn = document.getElementById('cameraBtn');
  const stopCameraBtn = document.getElementById('stopCameraBtn');
  const managementIdInput = document.getElementById('management_id');
  const studentIdInput = document.getElementById('student_id');

  // カメラボタン
  if (cameraBtn) {
    cameraBtn.addEventListener('click', () => {
      startCamera('management_id', (text) => {
        fetchEquipmentPreview(text);
        // スキャン後は学生ID欄にフォーカス（まだ未入力なら）
        if (studentIdInput && !studentIdInput.value) {
          studentIdInput.focus();
        }
      });
    });
  }

  if (stopCameraBtn) {
    stopCameraBtn.addEventListener('click', stopCamera);
  }

  // 管理IDが入力されたとき機材情報を取得
  if (managementIdInput) {
    let debounceTimer;
    managementIdInput.addEventListener('input', () => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        fetchEquipmentPreview(managementIdInput.value.trim());
      }, 400);
    });

    // バーコードリーダー（HID）はEnterを送出することが多い
    managementIdInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        fetchEquipmentPreview(managementIdInput.value.trim());
      }
    });
  }

  // 学生IDがEnterで次のフィールドへ
  if (studentIdInput) {
    studentIdInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        if (managementIdInput) managementIdInput.focus();
      }
    });
  }
});
