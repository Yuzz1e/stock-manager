document.addEventListener('DOMContentLoaded', () => {
  const managementIdInput = document.getElementById('management_id');
  const stepBarcode       = document.getElementById('stepBarcode');
  const nfcStatus         = document.getElementById('nfcStatus');
  const barcodeStatus     = document.getElementById('barcodeStatus');
  const sseStatus         = document.getElementById('sseStatus');

  // 返却は機材バーコードのみ → 常にアクティブ表示
  stepBarcode?.classList.add('scan-step--active-green');

  // --- スキャナー状態 UI 更新 ---
  function updateReaderStatus(data) {
    if (nfcStatus) {
      nfcStatus.textContent = data.nfc_connected ? '接続中' : '未接続';
      nfcStatus.className   = data.nfc_connected
        ? 'badge text-bg-success' : 'badge text-bg-secondary';
    }
    if (barcodeStatus) {
      barcodeStatus.textContent = data.serial_connected ? '接続中' : '未接続';
      barcodeStatus.className   = data.serial_connected
        ? 'badge text-bg-success' : 'badge text-bg-secondary';
    }
  }

  // --- SSE 接続 ---
  let evtSource = null;

  function connectSSE() {
    if (evtSource) evtSource.close();
    evtSource = new EventSource('/api/scan-events');

    evtSource.onopen = () => {
      if (sseStatus) {
        sseStatus.textContent = 'サーバー接続済';
        sseStatus.className   = 'badge text-bg-success ms-auto';
      }
    };

    evtSource.onerror = () => {
      if (sseStatus) {
        sseStatus.textContent = '再接続中...';
        sseStatus.className   = 'badge text-bg-warning ms-auto';
      }
    };

    // バーコードスキャン → 管理QRなら管理画面へ、それ以外は management_id に入力してプレビュー
    evtSource.addEventListener('barcode_scan', (e) => {
      const data = JSON.parse(e.data);
      const mid  = data.management_id || '';
      if (mid === '==INFOLAB_STOCK_MANAGEMENT_QR==') { window.location.href = '/admin'; return; }
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

  // --- キーボード / HIDリーダー 入力との互換 ---
  if (managementIdInput) {
    let debounceTimer;
    managementIdInput.addEventListener('input', () => {
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

  // タブ切り替え時の不要選択クリア
  document.getElementById('tabShelfBtn')?.addEventListener('click', () => {
    document.querySelectorAll('input[name="place_id"]').forEach(r => r.checked = false);
  });
  document.getElementById('tabPlaceBtn')?.addEventListener('click', () => {
    document.querySelectorAll('input[name="shelf_id"]').forEach(r => r.checked = false);
  });
});