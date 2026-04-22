/** フィールドをクリアしてフォーカスする */
function clearField(fieldId) {
  const el = document.getElementById(fieldId);
  if (el) {
    el.value = '';
    el.focus();
  }
}

/** 機材情報を非同期で取得してプレビューに表示する */
async function fetchEquipmentPreview(managementId) {
  const preview = document.getElementById('equipmentPreview');
  if (!preview) return;

  if (!managementId) {
    preview.classList.add('d-none');
    preview.innerHTML = '';
    return;
  }

  try {
    const res = await fetch('/api/equipment/lookup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ management_id: managementId }),
    });
    const data = await res.json();

    if (res.ok) {
      const i18n = window.I18N || {};
      const statusClass = data.status === '保管中' ? 'text-bg-success' : 'text-bg-warning';
      const statusLabel = data.status === '保管中'
        ? (i18n.status_storage || data.status)
        : (data.status === '使用中' ? (i18n.status_in_use || data.status) : data.status);
      const userLabel = i18n.user_label || '使用者: ';
      preview.innerHTML = `
        <div class="preview-box">
          <div class="d-flex align-items-center gap-2 flex-wrap">
            <span class="badge ${statusClass}">${statusLabel}</span>
            <strong>${data.management_id}</strong>
            <span>${data.item_name}</span>
            ${data.storage_label ? `<span class="shelf-badge">${data.storage_label}</span>` : ''}
            ${data.current_borrower ? `<span class="text-muted small">${userLabel}${data.current_borrower}</span>` : ''}
          </div>
        </div>`;
      preview.classList.remove('d-none');
    } else {
      preview.innerHTML = `<div class="preview-box preview-error"><i class="bi bi-exclamation-triangle me-1"></i>${data.error}</div>`;
      preview.classList.remove('d-none');
    }
  } catch {
    preview.classList.add('d-none');
  }
}