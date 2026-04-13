/**
 * Web Serial API を使ったシリアルポートバーコードリーダー共通モジュール。
 * Chrome / Edge 89+ が必要（localhost では HTTP でも動作）。
 *
 * 発行するカスタムイベント:
 *   connected    - 接続成功時
 *   disconnected - 切断時（正常・異常ともに）
 *   scan         - 1行スキャン完了時。e.detail に文字列
 *   error        - 読み取りエラー時。e.detail にメッセージ文字列
 */
class SerialScanner extends EventTarget {
  constructor() {
    super();
    this.port     = null;
    this.reader   = null;
    this._buffer  = '';
    this._running = false;
  }

  get isConnected() {
    return this._running;
  }

  /**
   * シリアルポートに接続する。
   * 過去に許可したポートがあれば自動選択し、なければ選択ダイアログを表示する。
   * @param {number} baudRate - ボーレート（デフォルト 9600）
   */
  async connect(baudRate = 9600) {
    if (!('serial' in navigator)) {
      throw new Error(
        'このブラウザは Web Serial API に対応していません。\n' +
        'Chrome または Edge をご利用ください。'
      );
    }
    const ports = await navigator.serial.getPorts();
    this.port = ports.length > 0
      ? ports[0]
      : await navigator.serial.requestPort();

    await this.port.open({ baudRate });
    this._running = true;
    this._readLoop();
    this.dispatchEvent(new CustomEvent('connected'));
  }

  async disconnect() {
    this._running = false;
    try { await this.reader?.cancel(); } catch {}
    this.reader = null;
    try { await this.port?.close(); } catch {}
    this.port    = null;
    this._buffer = '';
    this.dispatchEvent(new CustomEvent('disconnected'));
  }

  async _readLoop() {
    const decoder = new TextDecoder();
    while (this.port?.readable && this._running) {
      this.reader = this.port.readable.getReader();
      try {
        while (true) {
          const { value, done } = await this.reader.read();
          if (done) break;
          this._buffer += decoder.decode(value, { stream: true });
          let idx;
          while ((idx = this._buffer.search(/[\r\n]/)) !== -1) {
            const line = this._buffer.slice(0, idx).trim();
            this._buffer = this._buffer.slice(idx + 1).replace(/^[\r\n]+/, '');
            if (line) {
              this.dispatchEvent(new CustomEvent('scan', { detail: line }));
            }
          }
        }
      } catch (err) {
        if (this._running) {
          this.dispatchEvent(new CustomEvent('error', { detail: err.message }));
        }
      } finally {
        try { this.reader?.releaseLock(); } catch {}
        this.reader = null;
      }
    }
    this._running = false;
    this.port     = null;
    this._buffer  = '';
    this.dispatchEvent(new CustomEvent('disconnected'));
  }
}

const serialScanner = new SerialScanner();
