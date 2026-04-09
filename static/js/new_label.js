document.addEventListener('DOMContentLoaded', () => {
  const statusRadios = document.querySelectorAll('input[name="status"]');
  const storageArea = document.getElementById('storageArea');
  const inUseArea = document.getElementById('inUseArea');
  const categoryRadios = document.querySelectorAll('input[name="category_id"]');
  const idPreview = document.getElementById('idPreview');
  const idPreviewValue = document.getElementById('idPreviewValue');

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
});
