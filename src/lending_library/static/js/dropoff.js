/**
 * Drop-off intake for the Exeter lending library.
 *
 * Controls the three confirmation paths on /drop-off:
 * barcode scan, cover OCR, and typed ISBN or title search.
 *
 * Usage:
 *   Included by drop_off.html after ZXing and Tesseract scripts.
 */

const scanStatus = document.getElementById("scan-status");
const ocrStatus = document.getElementById("ocr-status");
const manualStatus = document.getElementById("manual-status");
const resultsRoot = document.getElementById("lookup-results");
const video = document.getElementById("barcode-video");
const startScanButton = document.getElementById("start-scan");
const stopScanButton = document.getElementById("stop-scan");
const coverInput = document.getElementById("cover-input");
const coverPreview = document.getElementById("cover-preview");
const manualForm = document.getElementById("manual-form");

let mediaStream = null;
let scanTimer = null;
let barcodeDetector = null;
let zxingReader = null;
let lastIsbn = "";

/**
 * Switch the visible intake panel and matching tab.
 *
 * @param {string} panelName - One of scan, cover, or manual.
 * @returns {void}
 */
function showPanel(panelName) {
  document.querySelectorAll(".method-tab").forEach((tab) => {
    tab.classList.toggle("is-active", tab.dataset.panel === panelName);
  });
  document.querySelectorAll(".intake-panel").forEach((panel) => {
    const active = panel.dataset.panel === panelName;
    panel.classList.toggle("is-active", active);
    panel.hidden = !active;
  });
  if (panelName !== "scan") {
    stopCamera();
  }
}

/**
 * Write a short status message next to an intake method.
 *
 * @param {HTMLElement} node - Status paragraph.
 * @param {string} message - Human-readable status.
 * @returns {void}
 */
function setStatus(node, message) {
  node.textContent = message;
}

/**
 * Fetch JSON from the FastAPI lookup and drop-off endpoints.
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
 * Render one or more bibliographic matches for student confirmation.
 *
 * @param {Array<object>} books - BookRecord objects from the API.
 * @param {string} heading - Section heading shown above the list.
 * @returns {void}
 */
function renderCandidates(books, heading) {
  resultsRoot.hidden = false;
  if (!books.length) {
    resultsRoot.innerHTML =
      "<div class='empty-state'><h2>No match found</h2><p>Try typing the title, or scan the barcode on the back of the book.</p></div>";
    return;
  }
  const items = books
    .map((book, index) => {
      const authors = (book.authors || []).join(", ") || "Unknown author";
      const isbn = book.isbn ? `<p>ISBN ${book.isbn}</p>` : "";
      const cover = book.cover_url
        ? `<img src="${book.cover_url}" alt="" referrerpolicy="no-referrer">`
        : `<div class="candidate-fallback">${(book.title || "?").slice(0, 1)}</div>`;
      return `<li class="candidate">
        ${cover}
        <div>
          <h3>${escapeHtml(book.title)}</h3>
          <p>${escapeHtml(authors)}</p>
          ${isbn}
        </div>
        <button type="button" class="btn btn-solid" data-confirm="${index}">This is the book</button>
      </li>`;
    })
    .join("");
  resultsRoot.innerHTML = `<h2>${escapeHtml(heading)}</h2><ul class="candidate-list">${items}</ul>`;
  resultsRoot.querySelectorAll("[data-confirm]").forEach((button) => {
    button.addEventListener("click", () => {
      confirmDropOff(books[Number(button.dataset.confirm)]);
    });
  });
}

/**
 * Escape text before inserting it into intake HTML.
 *
 * @param {string} value - Untrusted catalog string.
 * @returns {string} Escaped HTML text.
 */
function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

/**
 * Persist a confirmed book as one available copy, then open its detail page.
 *
 * @param {object} book - BookRecord chosen by the student.
 * @returns {Promise<void>}
 */
async function confirmDropOff(book) {
  setStatus(scanStatus, "Saving to the catalog…");
  setStatus(ocrStatus, "Saving to the catalog…");
  setStatus(manualStatus, "Saving to the catalog…");
  const payload = await api("/api/drop-off", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(book),
  });
  if (!payload.ok) {
    setStatus(manualStatus, payload.error || "Could not save this book.");
    return;
  }
  window.location.href = `/book/${payload.book_id}`;
}

/**
 * Look up a decoded or typed ISBN and show a confirmation card.
 *
 * @param {string} isbn - Raw ISBN or barcode text.
 * @returns {Promise<void>}
 */
async function lookupIsbn(isbn) {
  if (isbn === lastIsbn) {
    return;
  }
  lastIsbn = isbn;
  setStatus(scanStatus, `Looking up ISBN ${isbn}…`);
  const payload = await api(`/api/lookup/isbn/${encodeURIComponent(isbn)}`);
  if (!payload.ok || !payload.book) {
    setStatus(scanStatus, "No catalog match for that ISBN. Try the title instead.");
    showPanel("manual");
    document.getElementById("manual-isbn").value = isbn;
    return;
  }
  stopCamera();
  setStatus(scanStatus, "Confirm this title before it is added.");
  renderCandidates([payload.book], "Is this the book?");
}

/**
 * Search by title and author, then show up to five candidates.
 *
 * @param {object} params
 * @param {string} [params.q]
 * @param {string} [params.title]
 * @param {string} [params.author]
 * @param {HTMLElement} statusNode
 * @returns {Promise<void>}
 */
async function lookupSearch(params, statusNode) {
  const query = new URLSearchParams();
  if (params.q) query.set("q", params.q);
  if (params.title) query.set("title", params.title);
  if (params.author) query.set("author", params.author);
  setStatus(statusNode, "Searching the catalog…");
  const payload = await api(`/api/lookup/search?${query.toString()}`);
  if (!payload.books || !payload.books.length) {
    setStatus(statusNode, payload.error || "No matches. Check the spelling and try again.");
    renderCandidates([], "No match found");
    return;
  }
  setStatus(statusNode, "Choose the correct title.");
  renderCandidates(payload.books, "Choose the correct title");
}

/**
 * Open the rear camera and begin barcode detection.
 *
 * @returns {Promise<void>}
 */
async function startCamera() {
  stopCamera();
  mediaStream = await navigator.mediaDevices.getUserMedia({
    video: { facingMode: { ideal: "environment" } },
    audio: false,
  });
  video.srcObject = mediaStream;
  await video.play();
  startScanButton.hidden = true;
  stopScanButton.hidden = false;
  setStatus(scanStatus, "Point the camera at the barcode on the back of the book.");
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
            lookupIsbn(detected[0].rawValue);
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
        lookupIsbn(result.text);
      }
    });
    return;
  }
  setStatus(scanStatus, "This browser cannot scan barcodes. Type the ISBN instead.");
  showPanel("manual");
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

/**
 * Run Tesseract on a cover image file, then search by the extracted text.
 *
 * @param {File} file - Image captured or uploaded by the student.
 * @returns {Promise<void>}
 */
async function recognizeCover(file) {
  coverPreview.src = URL.createObjectURL(file);
  coverPreview.hidden = false;
  setStatus(ocrStatus, "Reading the cover… this can take a few seconds.");
  const worker = await window.Tesseract.createWorker("eng");
  const result = await worker.recognize(file);
  await worker.terminate();
  const payload = await api("/api/lookup/ocr", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text: result.data.text || "" }),
  });
  if (!payload.books || !payload.books.length) {
    const guessed = payload.parse && payload.parse.title ? ` Read “${payload.parse.title}”.` : "";
    setStatus(
      ocrStatus,
      (payload.error || "Could not match that cover.") + guessed + " Type the title instead."
    );
    showPanel("manual");
    if (payload.parse && payload.parse.title) {
      document.getElementById("manual-title").value = payload.parse.title;
    }
    if (payload.parse && payload.parse.author) {
      document.getElementById("manual-author").value = payload.parse.author;
    }
    return;
  }
  setStatus(ocrStatus, "Choose the correct title.");
  renderCandidates(payload.books, "Choose the correct title");
}

document.querySelectorAll(".method-tab").forEach((tab) => {
  tab.addEventListener("click", () => showPanel(tab.dataset.panel));
});

startScanButton.addEventListener("click", () => {
  const cameraStart = startCamera();
  cameraStart.then(
    () => undefined,
    () => setStatus(scanStatus, "Camera permission is required to scan a barcode.")
  );
});

stopScanButton.addEventListener("click", () => {
  stopCamera();
  setStatus(scanStatus, "Camera stopped.");
});

coverInput.addEventListener("change", () => {
  if (!coverInput.files || !coverInput.files[0]) {
    return;
  }
  const work = recognizeCover(coverInput.files[0]);
  work.then(
    () => undefined,
    () => setStatus(ocrStatus, "Could not read that image. Type the title instead.")
  );
});

manualForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const isbn = document.getElementById("manual-isbn").value.trim();
  const title = document.getElementById("manual-title").value.trim();
  const author = document.getElementById("manual-author").value.trim();
  if (isbn) {
    lastIsbn = "";
    const work = lookupIsbn(isbn);
    work.then(
      () => undefined,
      () => setStatus(manualStatus, "Lookup failed. Check the connection and try again.")
    );
    return;
  }
  if (!title) {
    setStatus(manualStatus, "Enter an ISBN or a title.");
    return;
  }
  const work = lookupSearch({ title, author, q: title }, manualStatus);
  work.then(
    () => undefined,
    () => setStatus(manualStatus, "Search failed. Check the connection and try again.")
  );
});

window.addEventListener("pagehide", stopCamera);
