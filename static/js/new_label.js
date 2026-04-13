document.addEventListener('DOMContentLoaded', () => {
  const statusRadios = document.querySelectorAll('input[name="status"]');
  const storageArea = document.getElementById('storageArea');
  const inUseArea = document.getElementById('inUseArea');
  const categoryRadios = document.querySelectorAll('input[name="category_id"]');
  const idPreview = document.getElementById('idPreview');
  const idPreviewValue = document.getElementById('idPreviewValue');
  const studentIdInput   = document.getElementById('student_id');
  const studentNameInput = document.getElementById('student_name');
  const nfcStatusBadge   = document.getElementById('nfcStatusBadge');
  const nfcScanPrompt    = document.getElementById('nfcScanPrompt');

  // ステータス切り替え
  function updateStatusArea() {
    const selected = document.querySelector('input[name="status"]:checked');
    if (!selected) return;
    if (selected.value === '保管中') {
      storageArea.classList.remove('d-none');
      inUseArea.classList.add('d-none');
    } else {
      storageArea.classList.add('d-none');
      inUseArea.classList.remove('d-none');
    }
  }

  statusRadios.forEach((r) => r.addEventListener('change', updateStatusArea));
  updateStatusArea();

  // カテゴリ選択時に発行予定IDをプレビュー
  async function updateIdPreview(categoryId) {
    if (!categoryId) {
      idPreview.classList.add('d-none');
      return;
    }
    try {
      const res = await fetch(`/api/next-number/${categoryId}`);
      const data = await res.json();
      if (res.ok) {
        idPreviewValue.textContent = data.management_id;
        idPreview.classList.remove('d-none');
      }
    } catch {
      idPreview.classList.add('d-none');
    }
  }

  categoryRadios.forEach((r) => {
    r.addEventListener('change', () => updateIdPreview(r.value));
    if (r.checked) updateIdPreview(r.value);
  });

  // 保管場所タブ切り替え時に不要な選択をクリア
  document.getElementById('nlTabShelfBtn')?.addEventListener('click', () => {
    document.querySelectorAll('input[name="place_id"]').forEach(r => r.checked = false);
  });
  document.getElementById('nlTabPlaceBtn')?.addEventListener('click', () => {
    document.querySelectorAll('input[name="shelf_id"]').forEach(r => r.checked = false);
  });

  // 用品ラベル: トグル表示
  const hasSupplyLabel   = document.getElementById('hasSupplyLabel');
  const supplyLabelFields = document.getElementById('supplyLabelFields');
  const supplyYearInput  = document.getElementById('supply_year');
  const supplyCodeInput  = document.getElementById('supply_code');
  const supplyYearPrev   = document.getElementById('supplyYearPreview');
  const supplyCodePrev   = document.getElementById('supplyCodePreview');

  function updateSupplyPreview() {
    if (supplyYearPrev) supplyYearPrev.textContent = supplyYearInput?.value.trim() || '____';
    if (supplyCodePrev) supplyCodePrev.textContent = supplyCodeInput?.value.trim() || '_____';
  }

  hasSupplyLabel?.addEventListener('change', () => {
    supplyLabelFields?.classList.toggle('d-none', !hasSupplyLabel.checked);
    if (!hasSupplyLabel.checked) {
      if (supplyYearInput) supplyYearInput.value = '';
      if (supplyCodeInput) supplyCodeInput.value = '';
      updateSupplyPreview();
    }
  });

  supplyYearInput?.addEventListener('input', updateSupplyPreview);
  supplyCodeInput?.addEventListener('input', updateSupplyPreview);

  // フォーム復元時の状態反映
  if (supplyCodeInput?.value || supplyYearInput?.value) {
    if (hasSupplyLabel) hasSupplyLabel.checked = true;
    supplyLabelFields?.classList.remove('d-none');
    updateSupplyPreview();
  }

  // --- NFC ステータスバッジ更新 ---
  function updateNfcStatus(connected) {
    if (!nfcStatusBadge) return;
    if (connected) {
      nfcStatusBadge.className = 'badge text-bg-success ms-auto';
      nfcStatusBadge.innerHTML = '<i class="bi bi-wifi me-1"></i>NFC 接続中';
    } else {
      nfcStatusBadge.className = 'badge text-bg-secondary ms-auto';
      nfcStatusBadge.innerHTML = '<i class="bi bi-wifi-off me-1"></i>NFC 未接続';
    }
  }

  // --- NFC 読み取り成功フラッシュ ---
  function flashNfcSuccess() {
    if (!nfcScanPrompt) return;
    nfcScanPrompt.className = 'alert alert-success d-flex align-items-center gap-2 py-2 mb-2';
    nfcScanPrompt.innerHTML = '<i class="bi bi-check-circle-fill fs-5 text-success"></i><span class="small">学生証を読み取りました</span>';
    setTimeout(() => {
      nfcScanPrompt.className = 'alert alert-info d-flex align-items-center gap-2 py-2 mb-2';
      nfcScanPrompt.innerHTML = '<i class="bi bi-credit-card-2-front fs-5 text-primary"></i><span class="small">学生証をNFCリーダーにかざすと自動入力されます</span>';
    }, 3000);
  }

  // --- SSE 接続（NFC スキャンイベント受信）---
  let evtSource = null;

  function connectSSE() {
    if (evtSource) evtSource.close();
    evtSource = new EventSource('/api/scan-events');

    evtSource.addEventListener('student_scan', (e) => {
      const data = JSON.parse(e.data);
      // 「使用中」選択中のときだけ自動入力する
      const isInUse = document.querySelector('input[name="status"]:checked')?.value === '使用中';
      if (!isInUse) return;
      if (studentIdInput)   studentIdInput.value   = data.student_id   || '';
      if (studentNameInput) studentNameInput.value = data.student_name || '';
      flashNfcSuccess();
    });

    evtSource.addEventListener('reader_status', (e) => {
      const data = JSON.parse(e.data);
      updateNfcStatus(!!data.nfc_connected);
    });
  }

  connectSSE();
  window.addEventListener('beforeunload', () => evtSource?.close());
});
