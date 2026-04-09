/**
 * html5-qrcode を使ったカメラスキャン共通処理
 * html5-qrcode は CDN から読み込むため、各ページのテンプレートで
 * <script src="https://unpkg.com/html5-qrcode"> を先に読み込むこと。
 */

let html5QrCode = null;

/**
 * カメラスキャンを開始する。
 * @param {string} targetInputId - スキャン結果を入力するINPUT要素のID
 * @param {Function} [onSuccess] - スキャン成功時のコールバック (text) => void
 */
function startCamera(targetInputId, onSuccess) {
  const cameraArea = document.getElementById('cameraArea');
  const readerDiv = document.getElementById('reader');

  if (!cameraArea || !readerDiv) return;

  cameraArea.classList.remove('d-none');

  // 既存のスキャナーを停止
  if (html5QrCode) {
    html5QrCode.stop().catch(() => {}).finally(() => {
      _initScanner(targetInputId, onSuccess);
    });
  } else {
    _initScanner(targetInputId, onSuccess);
  }
}

function _initScanner(targetInputId, onSuccess) {
  html5QrCode = new Html5Qrcode('reader');
  html5QrCode.start(
    { facingMode: 'environment' },
    { fps: 10, qrbox: { width: 250, height: 250 } },
    (decodedText) => {
      const input = document.getElementById(targetInputId);
      if (input) {
        input.value = decodedText;
        input.dispatchEvent(new Event('input', { bubbles: true }));
      }
      stopCamera();
      if (typeof onSuccess === 'function') {
        onSuccess(decodedText);
      }
    },
    () => {}
  ).catch((err) => {
    console.warn('カメラ起動エラー:', err);
    alert('カメラの起動に失敗しました。ブラウザの設定でカメラを許可してください。');
    stopCamera();
  });
}

function stopCamera() {
  const cameraArea = document.getElementById('cameraArea');
  if (html5QrCode) {
    html5QrCode.stop().catch(() => {}).finally(() => {
      html5QrCode = null;
      if (cameraArea) cameraArea.classList.add('d-none');
    });
  } else {
    if (cameraArea) cameraArea.classList.add('d-none');
  }
}

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
      const statusClass = data.status === '保管中' ? 'text-bg-success' : 'text-bg-warning';
      preview.innerHTML = `
        <div class="preview-box">
          <div class="d-flex align-items-center gap-2 flex-wrap">
            <span class="badge ${statusClass}">${data.status}</span>
            <strong>${data.management_id}</strong>
            <span>${data.item_name}</span>
            ${data.storage_label ? `<span class="shelf-badge">${data.storage_label}</span>` : ''}
            ${data.current_borrower ? `<span class="text-muted small">使用者: ${data.current_borrower}</span>` : ''}
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
