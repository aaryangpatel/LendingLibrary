/**
 * Pickup barcode scanner for the Exeter lending library.
 *
 * Scans an ISBN on /pickup and removes that title from the catalog.
 *
 * Usage:
 *   Included by pickup.html after the ZXing script.
 */

const scanStatus = document.getElementById("pickup-scan-status");
const video = document.getElementById("pickup-video");
const startScanButton = document.getElementById("pickup-start-scan");
const stopScanButton = document.getElementById("pickup-stop-scan");

let mediaStream = null;
let scanTimer = null;
let barcodeDetector = null;
let zxingReader = null;
let lastIsbn = "";
let removing = false;

/**
 * Write a short status message next to the pickup scanner.
 *
 * @param {string} message - Human-readable status.
 * @returns {void}
 */
function setStatus(message) {
  scanStatus.textContent = message;
}

/**
 * Fetch JSON from the pickup ISBN endpoint.
 *
 * @param {string} url - Request URL.
 * @param {RequestInit} [options] - Fetch options.
 * @returns {Promise<any>} Parsed JSON body.
 */
async function api(url, options) {
  const response = await fetch(url, options);
  return response.json();
}

/**
 * Remove a catalog copy that matches a scanned ISBN.
 *
 * @param {string} isbn - Raw ISBN or barcode text.
 * @returns {Promise<void>}
 */
async function pickupIsbn(isbn) {
  if (isbn === lastIsbn || removing) {
    return;
  }
  lastIsbn = isbn;
  removing = true;
  setStatus(`Removing ISBN ${isbn} from the catalog…`);
  const payload = await api(`/api/pickup/isbn/${encodeURIComponent(isbn)}`, {
    method: "POST",
  });
  if (!payload.ok) {
    removing = false;
    setStatus(payload.error || "That ISBN is not on the shelf.");
    return;
  }
  stopCamera();
  setStatus(`Removed “${payload.title}”.`);
  window.location.href = "/";
}

/**
 * Open the rear camera and begin barcode detection.
 *
 * @returns {Promise<void>}
 */
async function startCamera() {
  stopCamera();
  lastIsbn = "";
  removing = false;
  mediaStream = await navigator.mediaDevices.getUserMedia({
    video: { facingMode: { ideal: "environment" } },
    audio: false,
  });
  video.srcObject = mediaStream;
  await video.play();
  startScanButton.hidden = true;
  stopScanButton.hidden = false;
  setStatus("Point the camera at the barcode on the back of the book.");
  if ("BarcodeDetector" in window) {
    barcodeDetector = new window.BarcodeDetector({
      formats: ["ean_13", "ean_8", "upc_a", "upc_e", "code_128"],
    });
    const tick = () => {
      if (!barcodeDetector) {
        return;
      }
      barcodeDetector.detect(video).then(
        (detected) => {
          if (detected.length && detected[0].rawValue) {
            pickupIsbn(detected[0].rawValue);
          }
          if (barcodeDetector) {
            scanTimer = window.setTimeout(tick, 350);
          }
        },
        () => {
          if (barcodeDetector) {
            scanTimer = window.setTimeout(tick, 350);
          }
        }
      );
    };
    tick();
    return;
  }
  if (window.ZXing && window.ZXing.BrowserMultiFormatReader) {
    zxingReader = new window.ZXing.BrowserMultiFormatReader();
    zxingReader.decodeFromStream(mediaStream, video, (result) => {
      if (result && result.text) {
        pickupIsbn(result.text);
      }
    });
    return;
  }
  setStatus("This browser cannot scan barcodes. Search for the title instead.");
}

/**
 * Stop the camera and barcode loop.
 *
 * @returns {void}
 */
function stopCamera() {
  if (scanTimer) {
    window.clearTimeout(scanTimer);
    scanTimer = null;
  }
  if (zxingReader && zxingReader.reset) {
    zxingReader.reset();
  }
  zxingReader = null;
  barcodeDetector = null;
  if (mediaStream) {
    mediaStream.getTracks().forEach((track) => track.stop());
    mediaStream = null;
  }
  video.srcObject = null;
  startScanButton.hidden = false;
  stopScanButton.hidden = true;
}

startScanButton.addEventListener("click", () => {
  const cameraStart = startCamera();
  cameraStart.then(
    () => undefined,
    () => setStatus("Camera permission is required to scan a barcode.")
  );
});

stopScanButton.addEventListener("click", () => {
  stopCamera();
  setStatus("Camera stopped.");
});

window.addEventListener("pagehide", stopCamera);
