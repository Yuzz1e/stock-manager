document.addEventListener('DOMContentLoaded', () => {
  const cameraBtn = document.getElementById('cameraBtn');
  const stopCameraBtn = document.getElementById('stopCameraBtn');
  const managementIdInput = document.getElementById('management_id');

  if (cameraBtn) {
    cameraBtn.addEventListener('click', () => {
      startCamera('management_id', (text) => {
        fetchEquipmentPreview(text);
      });
    });
  }

  if (stopCameraBtn) {
    stopCameraBtn.addEventListener('click', stopCamera);
  }

  if (managementIdInput) {
    let debounceTimer;
    managementIdInput.addEventListener('input', () => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        fetchEquipmentPreview(managementIdInput.value.trim());
      }, 400);
    });

    managementIdInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        fetchEquipmentPreview(managementIdInput.value.trim());
      }
    });
  }
});
