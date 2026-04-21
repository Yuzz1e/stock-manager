document.addEventListener('DOMContentLoaded', () => {
  const studentIdInput    = document.getElementById('student_id');
  const studentNameInput  = document.getElementById('student_name');
  const managementIdInput = document.getElementById('management_id');
  const stepStudent       = document.getElementById('stepStudent');
  const stepBarcode       = document.getElementById('stepBarcode');
  const nfcStatus         = document.getElementById('nfcStatus');
  const barcodeStatus     = document.getElementById('barcodeStatus');
  const sseStatus         = document.getElementById('sseStatus');
  const confirmBtn        = document.getElementById('confirmBtn');

  // --- モーダルインスタンス ---
  const errorModal   = new bootstrap.Modal(document.getElementById('checkoutErrorModal'));
  const inUseModal   = new bootstrap.Modal(document.getElementById('inUseModal'));
  const forceBtn     = document.getElementById('forceCheckoutBtn');

  // 現在の送信データを保持（強制チェックアウト用）
  let _pendingPayload = null;

  // --- フェーズ管理 ---
  let phase = 'student';

  function setPhase(newPhase) {
    phase = newPhase;
    stepStudent?.classList.toggle('scan-step--active', phase === 'student');
    stepBarcode?.classList.toggle('scan-step--active', phase === 'barcode');
    if (phase === 'student') studentIdInput?.focus();
    else                     managementIdInput?.focus();
  }

  setPhase(studentIdInput?.value ? 'barcode' : 'student');

  // --- スキャナー状態 UI ---
  const I18N = window.I18N || {};

  function updateReaderStatus(data) {
    if (nfcStatus) {
      nfcStatus.textContent = data.nfc_connected ? I18N.connected : I18N.disconnected;
      nfcStatus.className   = data.nfc_connected
        ? 'badge text-bg-success' : 'badge text-bg-secondary';
    }
    if (barcodeStatus) {
      barcodeStatus.textContent = data.serial_connected ? I18N.connected : I18N.disconnected;
      barcodeStatus.className   = data.serial_connected
        ? 'badge text-bg-success' : 'badge text-bg-secondary';
    }
  }

  // --- 成功表示 ---
  function showSuccess(data) {
    document.getElementById('checkoutForm').classList.add('d-none');
    const successDiv = document.getElementById('checkoutSuccess');
    const detail     = document.getElementById('checkoutSuccessDetail');
    detail.innerHTML = `
      <div class="detail-row">
        <span class="detail-label">${I18N.equipment_label}</span>
        <span class="detail-value">${data.management_id} — ${data.item_name}</span>
      </div>
      <div class="detail-row">
        <span class="detail-label">${I18N.student_id_label}</span>
        <span class="detail-value">${data.student_id}</span>
      </div>
      ${data.student_name ? `<div class="detail-row"><span class="detail-label">${I18N.student_name_label}</span><span class="detail-value">${data.student_name}</span></div>` : ''}
    `;
    successDiv.classList.remove('d-none');
  }

  // --- エラーモーダル表示 ---
  function showErrorModal(message) {
    document.getElementById('errorModalMessage').textContent = message;
    errorModal.show();
  }

  // --- 使用中モーダル表示 ---
  function showInUseModal(resData) {
    document.getElementById('inUseMessage').textContent = resData.message;
    const name = resData.borrower_name
      ? `${resData.borrower_name}（${resData.borrower_id}）`
      : resData.borrower_id || (I18N.unknown || '不明');
    document.getElementById('inUseBorrower').textContent = name;
    inUseModal.show();
  }

  // --- フォーム送信（fetch） ---
  async function submitCheckout(url, payload) {
    if (confirmBtn) {
      confirmBtn.disabled    = true;
      confirmBtn.innerHTML   = `<span class="spinner-border spinner-border-sm me-2"></span>${I18N.processing}`;
    }
    try {
      const res  = await fetch(url, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify(payload),
      });
      const data = await res.json();

      if (res.ok && data.success) {
        showSuccess(data);
        return;
      }
      if (res.status === 409 && data.error === 'already_in_use') {
        _pendingPayload = payload;
        showInUseModal(data);
        return;
      }
      showErrorModal(data.error || I18N.error_occurred);
    } catch {
      showErrorModal(I18N.server_comm_failed);
    } finally {
      if (confirmBtn) {
        confirmBtn.disabled  = false;
        confirmBtn.innerHTML = `<i class="bi bi-check-lg me-2"></i>${I18N.confirm_register}`;
      }
    }
  }

  document.getElementById('checkoutForm')?.addEventListener('submit', (e) => {
    e.preventDefault();
    const payload = {
      student_id:    studentIdInput?.value.trim()    || '',
      management_id: managementIdInput?.value.trim() || '',
      student_name:  studentNameInput?.value.trim()  || '',
    };
    submitCheckout('/api/checkout', payload);
  });

  // --- 強制チェックアウト ---
  forceBtn?.addEventListener('click', async () => {
    if (!_pendingPayload) return;
    inUseModal.hide();
    await submitCheckout('/api/checkout/force', _pendingPayload);
    _pendingPayload = null;
  });

  // --- SSE 接続 ---
  let evtSource = null;

  function connectSSE() {
    if (evtSource) evtSource.close();
    evtSource = new EventSource('/api/scan-events');

    evtSource.onopen = () => {
      if (sseStatus) {
        sseStatus.textContent = I18N.server_connected;
        sseStatus.className   = 'badge text-bg-success ms-auto';
      }
    };
    evtSource.onerror = () => {
      if (sseStatus) {
        sseStatus.textContent = I18N.reconnecting;
        sseStatus.className   = 'badge text-bg-warning ms-auto';
      }
    };

    evtSource.addEventListener('student_scan', (e) => {
      const data = JSON.parse(e.data);
      if (studentIdInput)   studentIdInput.value   = data.student_id   || '';
      if (studentNameInput) studentNameInput.value = data.student_name || '';
      setPhase('barcode');
    });

    evtSource.addEventListener('barcode_scan', (e) => {
      const data = JSON.parse(e.data);
      const mid  = data.management_id || '';
      if (mid === '==INFOLAB_STOCK_MANAGEMENT_QR==') {
        window.location.href = '/admin';
        return;
      }
      if (managementIdInput) {
        managementIdInput.value = mid;
        fetchEquipmentPreview(mid);
      }
    });

    evtSource.addEventListener('reader_status', (e) => {
      updateReaderStatus(JSON.parse(e.data));
    });
  }

  connectSSE();
  window.addEventListener('beforeunload', () => evtSource?.close());

  // --- キーボード / HIDリーダー 入力互換 ---
  if (managementIdInput) {
    let debounceTimer;
    managementIdInput.addEventListener('focus',  () => setPhase('barcode'));
    managementIdInput.addEventListener('input',  () => {
      clearTimeout(debounceTimer);
      const v = managementIdInput.value.trim();
      debounceTimer = setTimeout(() => fetchEquipmentPreview(v), 400);
    });
    managementIdInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        fetchEquipmentPreview(managementIdInput.value.trim());
      }
    });
  }

  if (studentIdInput) {
    studentIdInput.addEventListener('focus',   () => setPhase('student'));
    studentIdInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); setPhase('barcode'); }
    });
  }
});

/** 「続けて登録」でフォームをリセットして再表示 */
function resetCheckout() {
  document.getElementById('checkoutSuccess').classList.add('d-none');
  const form = document.getElementById('checkoutForm');
  form.classList.remove('d-none');
  form.reset();
  document.getElementById('equipmentPreview')?.classList.add('d-none');
  document.getElementById('student_id')?.focus();
}