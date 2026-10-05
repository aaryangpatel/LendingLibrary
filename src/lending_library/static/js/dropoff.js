/**
 * Drop-off intake for the Exeter lending library.
 *
 * Controls the two confirmation paths on /drop-off:
 * barcode scan and typed ISBN or title search, including Load more pages.
 *
 * Usage:
 *   Included by drop_off.html after the ZXing script.
 */

const scanStatus = document.getElementById("scan-status");
const manualStatus = document.getElementById("manual-status");
const resultsRoot = document.getElementById("lookup-results");
const video = document.getElementById("barcode-video");
const startScanButton = document.getElementById("start-scan");
const stopScanButton = document.getElementById("stop-scan");
const manualForm = document.getElementById("manual-form");

let mediaStream = null;
let scanTimer = null;
let barcodeDetector = null;
let zxingReader = null;
let lastIsbn = "";
let displayedBooks = [];
let searchParams = { q: "", title: "", author: "" };
let searchHasMore = false;
let loadMoreBusy = false;

/**
 * Switch the visible intake panel and matching tab.
 *
 * @param {string} panelName - One of scan or manual.
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
 * Build HTML for one bibliographic candidate row.
 *
 * @param {object} book - BookRecord from the API.
 * @param {number} index - Index in displayedBooks used by the confirm button.
 * @returns {string} Candidate list-item markup.
 */
function candidateItemHtml(book, index) {
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
}

/**
 * Render one or more bibliographic matches for student confirmation.
 *
 * @param {Array<object>} books - BookRecord objects from the API.
 * @param {string} heading - Section heading shown above the list.
 * @param {boolean} [append=false] - When true, add this page under existing rows.
 * @param {boolean} [hasMore=false] - When true, show Load more titles.
 * @returns {void}
 */
function renderCandidates(books, heading, append, hasMore) {
  resultsRoot.hidden = false;
  if (!append) {
    displayedBooks = [];
  }
  const startIndex = displayedBooks.length;
  displayedBooks = displayedBooks.concat(books);
  if (!displayedBooks.length) {
    resultsRoot.innerHTML =
      "<div class='empty-state'><h2>No match found</h2><p>Try typing the title, or scan the barcode on the back of the book.</p></div>";
    return;
  }
  if (!append) {
    const items = displayedBooks
      .map((book, index) => candidateItemHtml(book, index))
      .join("");
    resultsRoot.innerHTML = `<h2>${escapeHtml(heading)}</h2><ul class="candidate-list">${items}</ul><div class="lookup-more" hidden><button type="button" class="btn btn-outline" id="load-more">Load more titles</button></div>`;
    const loadMoreButton = document.getElementById("load-more");
    loadMoreButton.addEventListener("click", () => {
      const work = lookupSearch(searchParams, manualStatus, true);
      work.then(
        () => undefined,
        () => setStatus(manualStatus, "Could not load more titles. Try again.")
      );
    });
  } else {
    const list = resultsRoot.querySelector(".candidate-list");
    const extra = books
      .map((book, index) => candidateItemHtml(book, startIndex + index))
      .join("");
    list.insertAdjacentHTML("beforeend", extra);
  }
  updateLoadMore(hasMore);
}

/**
 * Show or hide the Load more titles button after a search page.
 *
 * @param {boolean} hasMore - True when another search page exists.
 * @returns {void}
 */
function updateLoadMore(hasMore) {
  searchHasMore = Boolean(hasMore);
  const moreWrap = resultsRoot.querySelector(".lookup-more");
  if (!moreWrap) {
    return;
  }
  moreWrap.hidden = !searchHasMore;
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
  renderCandidates([payload.book], "Is this the book?", false, false);
}

/**
 * Search by title and author, then show one page of candidates.
 *
 * @param {object} params
 * @param {string} [params.q]
 * @param {string} [params.title]
 * @param {string} [params.author]
 * @param {HTMLElement} statusNode
 * @param {boolean} [append=false]
 * @returns {Promise<void>}
 */
async function lookupSearch(params, statusNode, append) {
  if (append && (loadMoreBusy || !searchHasMore)) {
    return;
  }
  searchParams = {
    q: params.q || "",
    title: params.title || "",
    author: params.author || "",
  };
  const query = new URLSearchParams();
  if (searchParams.q) query.set("q", searchParams.q);
  if (searchParams.title) query.set("title", searchParams.title);
  if (searchParams.author) query.set("author", searchParams.author);
  query.set("offset", String(append ? displayedBooks.length : 0));
  if (append) {
    loadMoreBusy = true;
    setStatus(statusNode, "Loading more titles…");
  } else {
    setStatus(statusNode, "Searching the catalog…");
  }
  const payload = await api(`/api/lookup/search?${query.toString()}`);
  loadMoreBusy = false;
  if (!payload.books || !payload.books.length) {
    if (append) {
      setStatus(statusNode, "No additional titles matched.");
      updateLoadMore(false);
      return;
    }
    setStatus(statusNode, payload.error || "No matches. Check the spelling and try again.");
    renderCandidates([], "No match found", false, false);
    return;
  }
  setStatus(statusNode, "Choose the matching title below. Load more if it is not listed.");
  renderCandidates(
    payload.books,
    "Choose the matching title",
    Boolean(append),
    Boolean(payload.has_more)
  );
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
  const work = lookupSearch({ title, author, q: title }, manualStatus, false);
  work.then(
    () => undefined,
    () => setStatus(manualStatus, "Search failed. Check the connection and try again.")
  );
});

resultsRoot.addEventListener("click", (event) => {
  const button = event.target.closest("[data-confirm]");
  if (!button) {
    return;
  }
  const book = displayedBooks[Number(button.dataset.confirm)];
  if (!book) {
    return;
  }
  confirmDropOff(book);
});

window.addEventListener("pagehide", stopCamera);
