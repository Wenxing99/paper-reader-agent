const shell = document.body;
const DEFAULT_MODEL = shell.dataset.defaultModel || "gpt-5.4";

function resolveInitialModel() {
    const storedModel = localStorage.getItem("paperReaderAgent.model");
    if (!storedModel) {
        return DEFAULT_MODEL;
    }
    return storedModel === "gpt-5.4-mini" ? DEFAULT_MODEL : storedModel;
}

const state = {
    papers: [],
    currentPaper: null,
    guideProgress: null,
    guidePollTimer: 0,
    guideToastPending: false,
    guideDeferredStart: false,
    guideWarmupPollTimer: 0,
    currentPage: 1,
    pageCache: {},
    pageRequests: new Map(),
    chatMessages: [],
    selectedText: "",
    selectedPage: 1,
    selectedRegion: null,
    viewerRequestToken: 0,
    pageObserver: null,
    pageVisibility: new Map(),
    settings: {
        bridgeUrl: localStorage.getItem("paperReaderAgent.bridgeUrl") || shell.dataset.defaultBridgeUrl || "http://127.0.0.1:8765/v1",
        model: resolveInitialModel(),
        apiKey: localStorage.getItem("paperReaderAgent.apiKey") || "",
        reasoningEffort: localStorage.getItem("paperReaderAgent.reasoningEffort") || shell.dataset.defaultReasoningEffort || "",
        libraryPath: localStorage.getItem("paperReaderAgent.libraryPath") || "",
    },
    reader: {
        mode: normalizeReaderMode(localStorage.getItem("paperReaderAgent.readerMode") || "continuous"),
        zoomMode: normalizeZoomMode(localStorage.getItem("paperReaderAgent.zoomMode") || "fit"),
        zoomScale: normalizeZoomScale(localStorage.getItem("paperReaderAgent.zoomScale") || "1"),
    },
    layout: {
        guideWidth: normalizeSidebarWidth(localStorage.getItem("paperReaderAgent.guideWidth"), 300, 220, 520),
        chatWidth: normalizeSidebarWidth(localStorage.getItem("paperReaderAgent.chatWidth"), 320, 260, 760),
        dragging: null,
    },
    pdf: {
        modulePromise: null,
        lib: null,
        documentPromise: null,
        loadingTask: null,
        document: null,
        documentUrl: "",
        renderGeneration: 0,
        activeTasks: new Map(),
        renderFrame: 0,
    },
};

const els = {
    workspace: document.getElementById("workspace"),
    pdfFileInput: document.getElementById("pdfFileInput"),
    libraryPathInput: document.getElementById("libraryPathInput"),
    scanLibraryButton: document.getElementById("scanLibraryButton"),
    paperSelect: document.getElementById("paperSelect"),
    generateGuideButton: document.getElementById("generateGuideButton"),
    bridgeUrlInput: document.getElementById("bridgeUrlInput"),
    modelInput: document.getElementById("modelInput"),
    reasoningEffortSelect: document.getElementById("reasoningEffortSelect"),
    apiKeyInput: document.getElementById("apiKeyInput"),
    guideTitle: document.getElementById("guideTitle"),
    guideStatus: document.getElementById("guideStatus"),
    guidePanel: document.getElementById("guidePanel"),
    guideResizeHandle: document.getElementById("guideResizeHandle"),
    paperTitle: document.getElementById("paperTitle"),
    paperMetaLine: document.getElementById("paperMetaLine"),
    continuousModeButton: document.getElementById("continuousModeButton"),
    singlePageModeButton: document.getElementById("singlePageModeButton"),
    zoomOutButton: document.getElementById("zoomOutButton"),
    fitWidthButton: document.getElementById("fitWidthButton"),
    zoomLabel: document.getElementById("zoomLabel"),
    zoomInButton: document.getElementById("zoomInButton"),
    prevPageButton: document.getElementById("prevPageButton"),
    nextPageButton: document.getElementById("nextPageButton"),
    pageSelect: document.getElementById("pageSelect"),
    viewerEmptyState: document.getElementById("viewerEmptyState"),
    viewerScrollViewport: document.getElementById("viewerScrollViewport"),
    viewerPages: document.getElementById("viewerPages"),
    viewerStatus: document.getElementById("viewerStatus"),
    chatResizeHandle: document.getElementById("chatResizeHandle"),
    chatContextBadge: document.getElementById("chatContextBadge"),
    chatMessages: document.getElementById("chatMessages"),
    chatInput: document.getElementById("chatInput"),
    chatSendButton: document.getElementById("chatSendButton"),
    selectionPopover: document.getElementById("selectionPopover"),
    popoverExplainButton: document.getElementById("popoverExplainButton"),
    popoverTranslateButton: document.getElementById("popoverTranslateButton"),
    toast: document.getElementById("toast"),
};

const PDFJS_BASE = "/static/vendor/pdfjs/";
const PDFJS_MODULE_URL = `${PDFJS_BASE}build/pdf.mjs`;
const PDFJS_WORKER_URL = `${PDFJS_BASE}build/pdf.worker.mjs`;
const MAX_CONTINUOUS_RENDER_PAGES = 4;
const INITIAL_CONTINUOUS_PAGE_LOAD_COUNT = 1;
const RICH_TEXT_MATH_DELIMITERS = [
    { left: "$$", right: "$$", display: true },
    { left: "\\[", right: "\\]", display: true },
    { left: "$", right: "$", display: false },
    { left: "\\(", right: "\\)", display: false },
];

function init() {
    els.bridgeUrlInput.value = state.settings.bridgeUrl;
    els.modelInput.value = state.settings.model;
    els.reasoningEffortSelect.value = normalizeReasoningEffort(state.settings.reasoningEffort);
    els.apiKeyInput.value = state.settings.apiKey;
    els.libraryPathInput.value = state.settings.libraryPath;
    applyWorkspaceLayout();

    els.pdfFileInput.addEventListener("change", handleUpload);
    els.scanLibraryButton.addEventListener("click", scanLibrary);
    els.paperSelect.addEventListener("change", (event) => {
        const paperId = event.target.value;
        if (paperId) {
            openPaper(paperId);
        }
    });
    els.generateGuideButton.addEventListener("click", generateReadingGuide);
    els.continuousModeButton.addEventListener("click", () => switchReaderMode("continuous"));
    els.singlePageModeButton.addEventListener("click", () => switchReaderMode("single"));
    els.zoomOutButton.addEventListener("click", () => adjustZoom(-0.12));
    els.zoomInButton.addEventListener("click", () => adjustZoom(0.12));
    els.fitWidthButton.addEventListener("click", fitToWidth);
    els.prevPageButton.addEventListener("click", () => changePage(state.currentPage - 1));
    els.nextPageButton.addEventListener("click", () => changePage(state.currentPage + 1));
    els.pageSelect.addEventListener("change", (event) => changePage(Number(event.target.value)));
    els.chatSendButton.addEventListener("click", sendChatMessage);
    els.chatInput.addEventListener("keydown", (event) => {
        if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
            event.preventDefault();
            sendChatMessage();
        }
    });
    els.bridgeUrlInput.addEventListener("change", persistSettings);
    els.modelInput.addEventListener("change", persistSettings);
    els.reasoningEffortSelect.addEventListener("change", persistSettings);
    els.apiKeyInput.addEventListener("change", persistSettings);
    els.libraryPathInput.addEventListener("change", persistSettings);

    els.viewerPages.addEventListener("mouseup", handleSelectionChange);
    els.viewerPages.addEventListener("keyup", handleSelectionChange);
    els.viewerScrollViewport.addEventListener("scroll", handleViewerScroll);
    els.guideResizeHandle.addEventListener("pointerdown", (event) => startResizeDrag("guide", event));
    els.chatResizeHandle.addEventListener("pointerdown", (event) => startResizeDrag("chat", event));
    window.addEventListener("resize", handleWindowResize);
    window.addEventListener("pointermove", handleResizePointerMove);
    window.addEventListener("pointerup", stopResizeDrag);
    window.addEventListener("pointercancel", stopResizeDrag);
    document.addEventListener("mousedown", handleDocumentMouseDown);
    els.selectionPopover.addEventListener("mousedown", (event) => {
        event.preventDefault();
    });
    els.popoverExplainButton.addEventListener("click", () => runSelectionAction("explain"));
    els.popoverTranslateButton.addEventListener("click", () => runSelectionAction("translate"));

    renderGuide(null);
    renderChat();
    renderViewer();
    refreshReaderHeader();
    loadPapers();
}

async function loadPapers(selectPaperId = null) {
    try {
        const data = await api("/api/papers");
        state.papers = data.papers || [];
        renderPaperSelect();
        if (selectPaperId) {
            await openPaper(selectPaperId);
        }
    }
    catch (error) {
        showToast(error.message);
    }
}

function applyCurrentPaperPayload(paper) {
    if (!paper) {
        return;
    }

    const currentPaper = state.currentPaper;
    const currentProgress = state.guideProgress;
    const mergedPaper = currentPaper ? { ...currentPaper, ...paper } : paper;
    if (currentPaper?.reading_guide && !paper.reading_guide) {
        mergedPaper.reading_guide = currentPaper.reading_guide;
    }

    const nextProgress = normalizeGuideProgress(paper.guide_progress || currentProgress);
    const shouldHoldDeferredProgress = (
        state.guideDeferredStart
        && paper.cache_state === "warming"
        && (!nextProgress || nextProgress.state === "idle" || nextProgress.state === "stale")
    );

    if (shouldHoldDeferredProgress || shouldPreserveGuideProgress(currentProgress, nextProgress)) {
        if (currentProgress) {
            mergedPaper.guide_progress = currentProgress;
        }
        state.currentPaper = mergedPaper;
        return;
    }

    state.currentPaper = mergedPaper;
    state.guideProgress = nextProgress;
}

function normalizeGuideProgress(progress) {
    if (!progress || typeof progress !== "object") {
        return null;
    }

    const stateValue = String(progress.state || "").trim().toLowerCase();
    if (!["idle", "stale", "running", "ready", "failed"].includes(stateValue)) {
        return null;
    }

    const steps = Array.isArray(progress.steps)
        ? progress.steps.map((step) => ({
            id: String(step?.id || "").trim(),
            label: String(step?.label || "").trim(),
            state: normalizeGuideStepState(step?.state),
        }))
        : [];

    return {
        state: stateValue,
        stage: String(progress.stage || "").trim(),
        stage_label: String(progress.stage_label || "").trim(),
        badge: String(progress.badge || "").trim(),
        message: String(progress.message || "").trim(),
        error: String(progress.error || "").trim(),
        updated_at: String(progress.updated_at || "").trim(),
        steps,
    };
}

function normalizeGuideStepState(value) {
    const stateValue = String(value || "").trim().toLowerCase();
    return ["pending", "current", "complete", "failed"].includes(stateValue) ? stateValue : "pending";
}

function isGuideProgressRunning(progress) {
    return Boolean(progress && progress.state === "running");
}

function guideProgressStageIndex(progress) {
    const stage = String(progress?.stage || "").trim();
    return ["prepare_text", "build_context", "draft_guide", "finalize"].indexOf(stage);
}

function shouldPreserveGuideProgress(currentProgress, nextProgress) {
    if (!currentProgress) {
        return false;
    }
    if (!nextProgress) {
        return ["running", "ready", "failed"].includes(currentProgress.state);
    }

    if (["ready", "failed"].includes(currentProgress.state) && ["idle", "stale"].includes(nextProgress.state)) {
        return true;
    }

    if (currentProgress.state === "running") {
        if (["idle", "stale"].includes(nextProgress.state)) {
            return true;
        }
        if (nextProgress.state === "running") {
            const currentIndex = guideProgressStageIndex(currentProgress);
            const nextIndex = guideProgressStageIndex(nextProgress);
            if (currentIndex > nextIndex && nextIndex >= 0) {
                return true;
            }
        }
    }

    return false;
}

function buildDeferredGuideProgress() {
    return {
        state: "running",
        stage: "prepare_text",
        stage_label: "读取论文",
        badge: "准备中",
        message: "全文文本层仍在后台准备，准备好后会自动开始生成阅读导图。",
        error: "",
        updated_at: new Date().toISOString(),
        steps: [
            { id: "prepare_text", label: "读取论文", state: "current" },
            { id: "build_context", label: "构建全文上下文", state: "pending" },
            { id: "draft_guide", label: "生成分段摘要", state: "pending" },
            { id: "finalize", label: "合成阅读导图", state: "pending" },
        ],
    };
}

function stopDeferredGuideStart() {
    if (state.guideWarmupPollTimer) {
        window.clearTimeout(state.guideWarmupPollTimer);
        state.guideWarmupPollTimer = 0;
    }
    state.guideDeferredStart = false;
}

async function requestReadingGuideGeneration() {
    if (!state.currentPaper) {
        return;
    }

    setBusy(els.generateGuideButton, true, "生成中...");

    try {
        const data = await api(`/api/papers/${state.currentPaper.id}/reading-guide`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(requestConfigBody()),
        });

        applyCurrentPaperPayload(data.paper);
        state.guideProgress = normalizeGuideProgress(data.status || state.currentPaper?.guide_progress);
        if (data.reading_guide && state.currentPaper) {
            state.currentPaper.reading_guide = data.reading_guide;
        }

        renderGuide(state.currentPaper?.reading_guide || null);
        refreshReaderHeader();

        if (data.reading_guide || state.guideProgress?.state === "ready") {
            state.guideToastPending = false;
            showToast("阅读导图已生成。");
        }
        else if (isGuideProgressRunning(state.guideProgress) && state.currentPaper) {
            startGuidePolling(state.currentPaper.id);
        }
        else if (state.guideProgress?.state === "failed") {
            state.guideToastPending = false;
            showToast(state.guideProgress.error || "生成阅读导图失败。");
        }
    }
    catch (error) {
        state.guideToastPending = false;
        els.guideStatus.textContent = "失败";
        showToast(error.message);
    }
    finally {
        updateActionAvailability();
    }
}

function startDeferredGuideStart() {
    stopDeferredGuideStart();
    if (!state.currentPaper) {
        return;
    }

    const paperId = state.currentPaper.id;
    state.guideDeferredStart = true;
    state.guideProgress = buildDeferredGuideProgress();
    renderGuide(state.currentPaper?.reading_guide || null);
    refreshReaderHeader();
    updateActionAvailability();

    const pollCacheWarmup = async () => {
        if (!state.currentPaper || state.currentPaper.id !== paperId || !state.guideDeferredStart) {
            stopDeferredGuideStart();
            return;
        }

        try {
            const data = await api(`/api/papers/${paperId}`);
            if (!state.currentPaper || state.currentPaper.id !== paperId || !state.guideDeferredStart) {
                stopDeferredGuideStart();
                return;
            }

            applyCurrentPaperPayload(data.paper);
            if (state.currentPaper.cache_state === "warming") {
                state.guideProgress = buildDeferredGuideProgress();
                renderGuide(state.currentPaper?.reading_guide || null);
                refreshReaderHeader();
                updateActionAvailability();
                state.guideWarmupPollTimer = window.setTimeout(() => {
                    void pollCacheWarmup();
                }, 1000);
                return;
            }

            state.guideProgress = {
                ...buildDeferredGuideProgress(),
                badge: "\u542f\u52a8\u4e2d",
                message: "\u5168\u6587\u6587\u672c\u5c42\u5df2\u51c6\u5907\u597d\uff0c\u6b63\u5728\u542f\u52a8\u9605\u8bfb\u5bfc\u56fe\u751f\u6210\u3002",
                updated_at: new Date().toISOString(),
            };
            renderGuide(state.currentPaper?.reading_guide || null);
            refreshReaderHeader();
            updateActionAvailability();
            await requestReadingGuideGeneration();
            if (state.guideDeferredStart && !isGuideProgressRunning(state.guideProgress)) {
                stopDeferredGuideStart();
            }
        }
        catch (error) {
            stopDeferredGuideStart();
            state.guideToastPending = false;
            state.guideProgress = normalizeGuideProgress(state.currentPaper?.guide_progress);
            renderGuide(state.currentPaper?.reading_guide || null);
            updateActionAvailability();
            showToast(error.message);
        }
    };

    void pollCacheWarmup();
}

function stopGuidePolling() {
    if (state.guidePollTimer) {
        window.clearTimeout(state.guidePollTimer);
        state.guidePollTimer = 0;
    }
}

function startGuidePolling(paperId) {
    stopGuidePolling();
    stopDeferredGuideStart();
    if (!paperId) {
        return;
    }

    const pollStatus = async () => {
        if (!state.currentPaper || state.currentPaper.id !== paperId) {
            stopGuidePolling();
            return;
        }

        try {
            const data = await api(`/api/papers/${paperId}/reading-guide-status`);
            if (!state.currentPaper || state.currentPaper.id !== paperId) {
                stopGuidePolling();
                return;
            }

            applyCurrentPaperPayload(data.paper);
            state.guideProgress = normalizeGuideProgress(data.status || state.currentPaper?.guide_progress);
            renderGuide(state.currentPaper?.reading_guide || null);
            refreshReaderHeader();
            updateActionAvailability();

            if (isGuideProgressRunning(state.guideProgress)) {
                state.guidePollTimer = window.setTimeout(() => {
                    void pollStatus();
                }, 1200);
                return;
            }

            stopGuidePolling();
            if (state.guideProgress?.state === "ready") {
                if (state.guideToastPending) {
                    showToast("阅读导图已生成。");
                }
            }
            else if (state.guideProgress?.state === "failed") {
                if (state.guideToastPending) {
                    showToast(state.guideProgress.error || "生成阅读导图失败。");
                }
            }
            state.guideToastPending = false;
        }
        catch (error) {
            stopGuidePolling();
            if (state.guideToastPending) {
                showToast(error.message);
            }
            state.guideToastPending = false;
            updateActionAvailability();
        }
    };

    void pollStatus();
}

function renderPaperSelect() {
    const activeId = state.currentPaper?.id || "";
    const options = ['<option value="">选择论文…</option>'];
    for (const paper of state.papers) {
        const selected = activeId === paper.id ? " selected" : "";
        options.push(`<option value="${paper.id}"${selected}>${escapeHtml(paper.title)} · ${escapeHtml(paper.source_label || paper.filename)}</option>`);
    }
    els.paperSelect.innerHTML = options.join("");
}

async function handleUpload(event) {
    const file = event.target.files?.[0];
    if (!file) {
        return;
    }

    const formData = new FormData();
    formData.append("file", file);
    setBusy(els.generateGuideButton, true, "导入中...");
    try {
        const data = await api("/api/library/import", {
            method: "POST",
            body: formData,
        });
        els.pdfFileInput.value = "";
        showToast(`已导入 ${data.paper.title}`);
        await loadPapers(data.paper.id);
    }
    catch (error) {
        showToast(error.message);
    }
    finally {
        setBusy(els.generateGuideButton, false, "生成阅读导图");
        updateActionAvailability();
    }
}

async function scanLibrary() {
    persistSettings();
    const folderPath = state.settings.libraryPath.trim();
    if (!folderPath) {
        showToast("请先填写本地论文目录路径。");
        return;
    }

    setBusy(els.scanLibraryButton, true, "扫描中...");
    try {
        const data = await api("/api/library/scan", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ folder_path: folderPath }),
        });
        state.papers = data.papers || [];
        renderPaperSelect();
        if (!state.currentPaper && state.papers.length) {
            await openPaper(state.papers[0].id);
        }
        showToast(`已扫描 ${state.papers.length} 篇论文。`);
    }
    catch (error) {
        showToast(error.message);
    }
    finally {
        setBusy(els.scanLibraryButton, false, "扫描目录");
    }
}

async function openPaper(paperId) {
    try {
        const data = await api(`/api/papers/${paperId}`);
        stopGuidePolling();
        stopDeferredGuideStart();
        resetPdfDocument();
        state.currentPaper = data.paper || null;
        state.guideProgress = normalizeGuideProgress(data.paper?.guide_progress);
        state.currentPage = 1;
        state.pageCache = {};
        state.pageRequests = new Map();
        state.chatMessages = [];
        state.selectedText = "";
        state.selectedPage = 1;
        state.selectedRegion = null;
        state.guideToastPending = false;
        state.viewerRequestToken += 1;
        disconnectPageObserver();
        state.pageVisibility.clear();

        renderPaperSelect();
        renderGuide(state.currentPaper?.reading_guide || null);
        populatePageSelect();
        renderChat();
        refreshReaderHeader();
        renderViewer();
        updateActionAvailability();
        clearSelection();

        if (isGuideProgressRunning(state.guideProgress) && state.currentPaper) {
            startGuidePolling(state.currentPaper.id);
        }

        await loadReaderForCurrentMode({ scrollToCurrent: true, behavior: "auto" });
    }
    catch (error) {
        showToast(error.message);
    }
}

function populatePageSelect() {
    if (!state.currentPaper) {
        els.pageSelect.innerHTML = "";
        els.pageSelect.disabled = true;
        return;
    }

    const options = [];
    for (let page = 1; page <= state.currentPaper.page_count; page += 1) {
        options.push(`<option value="${page}">第 ${page} 页</option>`);
    }
    els.pageSelect.innerHTML = options.join("");
    els.pageSelect.disabled = false;
    els.pageSelect.value = String(state.currentPage);
}

async function loadReaderForCurrentMode({ scrollToCurrent = false, behavior = "auto" } = {}) {
    if (!state.currentPaper) {
        return;
    }

    const token = ++state.viewerRequestToken;
    renderViewer();

    try {
        const targetPages = state.reader.mode === "continuous"
            ? getInitialContinuousPageNumbers()
            : [state.currentPage];
        await Promise.all([
            ensurePagesLoaded(targetPages),
            ensurePdfDocumentReady(),
        ]);
        if (token !== state.viewerRequestToken) {
            return;
        }
        renderViewer();
        scheduleVisiblePageRenders();
        if (scrollToCurrent) {
            if (state.reader.mode === "continuous") {
                scrollToPage(state.currentPage, behavior);
            }
            else {
                els.viewerScrollViewport.scrollTop = 0;
            }
        }
    }
    catch (error) {
        if (token !== state.viewerRequestToken) {
            return;
        }
        showToast(error.message);
        els.viewerStatus.textContent = error.message;
    }
}

async function ensurePagesLoaded(pageNumbers, { silent = false } = {}) {
    const uniquePageNumbers = Array.from(new Set(pageNumbers.filter(Boolean)));
    if (!uniquePageNumbers.length) {
        return [];
    }

    const missingPageNumbers = uniquePageNumbers.filter((pageNumber) => !state.pageCache[pageNumber]);
    if (!silent && missingPageNumbers.length) {
        if (state.reader.mode === "continuous") {
            els.viewerStatus.textContent = `正在准备首批页面（${missingPageNumbers.length} 页）...`;
        }
        else {
            els.viewerStatus.textContent = `正在加载第 ${state.currentPage} 页...`;
        }
    }

    const pagePayloads = await Promise.all(uniquePageNumbers.map((pageNumber) => ensurePageLoaded(pageNumber)));
    updateViewerStatus();
    return pagePayloads.filter(Boolean);
}

async function ensurePageLoaded(pageNumber) {
    if (state.pageCache[pageNumber]) {
        return state.pageCache[pageNumber];
    }

    const existingRequest = state.pageRequests.get(pageNumber);
    if (existingRequest) {
        return existingRequest;
    }

    const paperId = state.currentPaper?.id;
    if (!paperId) {
        return null;
    }

    const requestPromise = loadPageData(pageNumber, paperId)
        .then((data) => {
            if (state.currentPaper?.id !== paperId) {
                return null;
            }
            if (data.paper) {
                applyCurrentPaperPayload(data.paper);
            }
            const page = data.page || null;
            if (!page) {
                return null;
            }
            const hadPage = Boolean(state.pageCache[page.page_number]);
            state.pageCache[page.page_number] = page;
            if (!hadPage) {
                hydratePageCard(page.page_number);
            }
            return page;
        })
        .finally(() => {
            if (state.pageRequests.get(pageNumber) === requestPromise) {
                state.pageRequests.delete(pageNumber);
            }
        });

    state.pageRequests.set(pageNumber, requestPromise);
    return requestPromise;
}

async function loadPageData(pageNumber, paperId = state.currentPaper?.id) {
    const data = await api(`/api/papers/${paperId}/pages/${pageNumber}`);
    return data;
}

function getInitialContinuousPageNumbers() {
    if (!state.currentPaper) {
        return [];
    }

    const ordered = [state.currentPage, state.currentPage + 1, state.currentPage - 1, state.currentPage + 2, state.currentPage + 3];
    const unique = [];
    for (const pageNumber of ordered) {
        if (pageNumber < 1 || pageNumber > state.currentPaper.page_count || unique.includes(pageNumber)) {
            continue;
        }
        unique.push(pageNumber);
        if (unique.length >= INITIAL_CONTINUOUS_PAGE_LOAD_COUNT) {
            break;
        }
    }
    return unique;
}

function applyWorkspaceLayout({ persist = false } = {}) {
    if (!els.workspace) {
        return;
    }

    if (!isDesktopWorkspace()) {
        els.workspace.style.setProperty("--guide-width", `${state.layout.guideWidth}px`);
        els.workspace.style.setProperty("--chat-width", `${state.layout.chatWidth}px`);
        if (persist) {
            persistLayoutPreferences();
        }
        return;
    }

    const totalWidth = els.workspace.clientWidth || window.innerWidth;
    const centerMinWidth = 560;
    const resizerTotal = 24;

    let guideWidth = normalizeSidebarWidth(state.layout.guideWidth, 300, 220, 520);
    let chatWidth = normalizeSidebarWidth(state.layout.chatWidth, 320, 260, 760);

    const maxGuideWidth = Math.max(220, totalWidth - chatWidth - centerMinWidth - resizerTotal);
    guideWidth = clampNumber(guideWidth, 220, maxGuideWidth);

    const maxChatWidth = Math.max(260, totalWidth - guideWidth - centerMinWidth - resizerTotal);
    chatWidth = clampNumber(chatWidth, 260, maxChatWidth);

    const adjustedMaxGuideWidth = Math.max(220, totalWidth - chatWidth - centerMinWidth - resizerTotal);
    guideWidth = clampNumber(guideWidth, 220, adjustedMaxGuideWidth);

    state.layout.guideWidth = guideWidth;
    state.layout.chatWidth = chatWidth;

    els.workspace.style.setProperty("--guide-width", `${guideWidth}px`);
    els.workspace.style.setProperty("--chat-width", `${chatWidth}px`);

    if (persist) {
        persistLayoutPreferences();
    }
}

function startResizeDrag(side, event) {
    if (!isDesktopWorkspace()) {
        return;
    }

    event.preventDefault();
    state.layout.dragging = { side };
    els.workspace.classList.add("is-resizing");
}

function handleResizePointerMove(event) {
    if (!state.layout.dragging || !isDesktopWorkspace()) {
        return;
    }

    const rect = els.workspace.getBoundingClientRect();
    const totalWidth = rect.width;
    const centerMinWidth = 560;
    const resizerTotal = 24;

    if (state.layout.dragging.side === "guide") {
        const maxGuideWidth = Math.max(220, totalWidth - state.layout.chatWidth - centerMinWidth - resizerTotal);
        const nextGuideWidth = clampNumber(event.clientX - rect.left - 6, 220, maxGuideWidth);
        state.layout.guideWidth = nextGuideWidth;
    }
    else {
        const maxChatWidth = Math.max(260, totalWidth - state.layout.guideWidth - centerMinWidth - resizerTotal);
        const nextChatWidth = clampNumber(rect.right - event.clientX - 6, 260, maxChatWidth);
        state.layout.chatWidth = nextChatWidth;
    }

    applyWorkspaceLayout();
}

function stopResizeDrag() {
    if (!state.layout.dragging) {
        return;
    }

    state.layout.dragging = null;
    els.workspace.classList.remove("is-resizing");
    applyWorkspaceLayout({ persist: true });
}

async function switchReaderMode(mode) {
    const nextMode = normalizeReaderMode(mode);
    if (state.reader.mode === nextMode && !state.currentPaper) {
        refreshReaderHeader();
        return;
    }

    state.reader.mode = nextMode;
    persistReaderPreferences();
    clearSelection();
    refreshReaderHeader();

    if (!state.currentPaper) {
        renderViewer();
        return;
    }

    await loadReaderForCurrentMode({ scrollToCurrent: true, behavior: "auto" });
}

async function changePage(pageNumber) {
    if (!state.currentPaper || pageNumber < 1 || pageNumber > state.currentPaper.page_count) {
        return;
    }

    const hadPage = Boolean(state.pageCache[pageNumber]);
    state.currentPage = pageNumber;
    refreshReaderHeader();
    clearSelection();

    if (state.reader.mode === "continuous") {
        try {
            await ensurePagesLoaded([pageNumber]);
            if (!hadPage) {
                updateViewerStatus();
            }
            scrollToPage(pageNumber, "smooth");
        }
        catch (error) {
            showToast(error.message);
        }
        return;
    }

    await loadReaderForCurrentMode({ scrollToCurrent: true, behavior: "auto" });
}

function renderViewer() {
    if (!state.currentPaper) {
        els.viewerEmptyState.classList.remove("hidden");
        els.viewerScrollViewport.classList.add("hidden");
        els.viewerPages.innerHTML = "";
        disconnectPageObserver();
        updateZoomControls();
        return;
    }

    const pageNumbers = state.reader.mode === "continuous"
        ? listAllPageNumbers()
        : [state.currentPage];

    els.viewerEmptyState.classList.add("hidden");
    els.viewerScrollViewport.classList.remove("hidden");
    els.viewerPages.className = `viewer-pages ${state.reader.mode === "continuous" ? "continuous-mode" : "single-mode"}`;
    els.viewerPages.innerHTML = pageNumbers.map((pageNumber) => renderPageCard(pageNumber)).join("");
    syncViewerScale();
    setupPageObserver();
    updateViewerStatus();
    refreshReaderHeader();
}

function renderPageCard(pageNumber) {
    const page = state.pageCache[pageNumber];
    if (!page) {
        return `
            <section class="paper-page paper-page--placeholder" data-page-number="${pageNumber}">
                <div class="page-frame">
                    <div class="page-stage">
                        <div class="page-placeholder">正在准备第 ${pageNumber} 页…</div>
                    </div>
                </div>
                <p class="page-caption">第 ${pageNumber} 页</p>
            </section>
        `;
    }

    return `
        <section class="paper-page is-loading" data-page-number="${pageNumber}">
            <div class="page-frame">
                <div class="page-stage">
                    <canvas class="page-canvas" data-page-number="${pageNumber}" aria-label="PDF page ${pageNumber}"></canvas>
                    <div class="page-loading-shell" aria-hidden="true">
                        <span class="page-loading-label">正在渲染第 ${pageNumber} 页…</span>
                    </div>
                    <div class="page-text-layer" data-page-number="${pageNumber}">
                        ${(page.lines || []).map((line) => renderLine(line)).join("")}
                    </div>
                </div>
            </div>
            <p class="page-caption">第 ${pageNumber} 页</p>
        </section>
    `;
}

function renderLine(line) {
    const style = [
        `left:${line.x}px`,
        `top:${line.y}px`,
        `width:${line.width}px`,
        `height:${line.height}px`,
        `font-size:${Math.max(line.font_size * 0.92, 8)}px`,
    ].join(";");
    return `<span class="page-line" style="${style}">${escapeHtml(line.text)}</span>`;
}

function syncViewerScale() {
    const pageNodes = els.viewerPages.querySelectorAll(".paper-page");
    for (const pageNode of pageNodes) {
        syncPageNodeScale(pageNode);
    }
    scheduleVisiblePageRenders();
    updateZoomControls();
}

function syncPageNodeScale(pageNode) {
    const pageNumber = Number(pageNode.dataset.pageNumber || 0);
    const metrics = state.pageCache[pageNumber] || getEstimatedPageMetrics();
    if (!metrics) {
        return;
    }

    const scale = getScaleForPage(metrics);
    const frame = pageNode.querySelector(".page-frame");
    const stage = pageNode.querySelector(".page-stage");
    if (!frame || !stage) {
        return;
    }

    frame.style.width = `${metrics.width * scale}px`;
    frame.style.height = `${metrics.height * scale}px`;
    stage.style.width = `${metrics.width * scale}px`;
    stage.style.height = `${metrics.height * scale}px`;

    const canvas = pageNode.querySelector(".page-canvas");
    const textLayer = pageNode.querySelector(".page-text-layer");
    if (canvas) {
        canvas.style.width = `${metrics.width * scale}px`;
        canvas.style.height = `${metrics.height * scale}px`;
    }
    if (textLayer) {
        textLayer.style.width = `${metrics.width}px`;
        textLayer.style.height = `${metrics.height}px`;
        textLayer.style.transform = `scale(${scale})`;
    }
}

function hydratePageCard(pageNumber) {
    const existingNode = els.viewerPages.querySelector(`.paper-page[data-page-number="${pageNumber}"]`);
    if (!existingNode) {
        return;
    }

    const template = document.createElement("template");
    template.innerHTML = renderPageCard(pageNumber).trim();
    const nextNode = template.content.firstElementChild;
    if (!nextNode) {
        return;
    }

    if (state.pageObserver && state.reader.mode === "continuous") {
        state.pageObserver.unobserve(existingNode);
    }
    existingNode.replaceWith(nextNode);
    syncPageNodeScale(nextNode);
    if (state.pageObserver && state.reader.mode === "continuous") {
        state.pageObserver.observe(nextNode);
    }
    scheduleVisiblePageRenders();
}

function getEstimatedPageMetrics() {
    return getReferencePage() || { width: 612, height: 792 };
}

function setupPageObserver() {
    disconnectPageObserver();
    state.pageVisibility.clear();

    if (state.reader.mode !== "continuous" || !window.IntersectionObserver) {
        return;
    }

    state.pageObserver = new IntersectionObserver(handlePageIntersections, {
        root: els.viewerScrollViewport,
        rootMargin: "90% 0px",
        threshold: [0.2, 0.45, 0.7, 0.9],
    });

    for (const pageNode of els.viewerPages.querySelectorAll(".paper-page")) {
        state.pageObserver.observe(pageNode);
    }
}

function disconnectPageObserver() {
    if (state.pageObserver) {
        state.pageObserver.disconnect();
        state.pageObserver = null;
    }
}

function handlePageIntersections(entries) {
    for (const entry of entries) {
        const pageNumber = Number(entry.target.dataset.pageNumber || 0);
        if (!pageNumber) {
            continue;
        }
        state.pageVisibility.set(pageNumber, entry.isIntersecting ? entry.intersectionRatio : 0);
    }

    let bestPage = state.currentPage;
    let bestRatio = -1;
    for (const [pageNumber, ratio] of state.pageVisibility.entries()) {
        if (ratio > bestRatio) {
            bestPage = pageNumber;
            bestRatio = ratio;
        }
    }

    if (bestRatio >= 0 && bestPage !== state.currentPage) {
        state.currentPage = bestPage;
        refreshReaderHeader();
        updateViewerStatus();
    }
    scheduleVisiblePageRenders();
}

function scrollToPage(pageNumber, behavior = "smooth") {
    const target = els.viewerPages.querySelector(`.paper-page[data-page-number="${pageNumber}"]`);
    if (!target) {
        return;
    }

    requestAnimationFrame(() => {
        els.viewerScrollViewport.scrollTo({
            top: Math.max(0, target.offsetTop - 8),
            behavior,
        });
    });
}

function adjustZoom(delta) {
    const referencePage = getReferencePage();
    const currentScale = state.reader.zoomMode === "fit" && referencePage
        ? getFitWidthScale(referencePage)
        : state.reader.zoomScale;

    state.reader.zoomMode = "manual";
    state.reader.zoomScale = clampZoomScale(currentScale + delta);
    persistReaderPreferences();
    syncViewerScale();
    updateViewerStatus();
}

function fitToWidth() {
    state.reader.zoomMode = "fit";
    persistReaderPreferences();
    syncViewerScale();
    updateViewerStatus();
}

function updateZoomControls() {
    const activeScale = getActiveScale();
    els.zoomLabel.textContent = `${Math.round(activeScale * 100)}%`;
    els.fitWidthButton.classList.toggle("is-active", state.reader.zoomMode === "fit");
    els.continuousModeButton.classList.toggle("is-active", state.reader.mode === "continuous");
    els.singlePageModeButton.classList.toggle("is-active", state.reader.mode === "single");
}

function getActiveScale() {
    const referencePage = getReferencePage();
    if (!referencePage) {
        return state.reader.zoomMode === "fit" ? 1 : state.reader.zoomScale;
    }
    return getScaleForPage(referencePage);
}

function getScaleForPage(page) {
    if (state.reader.zoomMode === "fit") {
        return getFitWidthScale(page);
    }
    return clampZoomScale(state.reader.zoomScale);
}

function getFitWidthScale(page) {
    const availableWidth = Math.max(320, els.viewerScrollViewport.clientWidth - 44);
    return clampZoomScale(availableWidth / page.width);
}

function getReferencePage() {
    if (state.pageCache[state.currentPage]) {
        return state.pageCache[state.currentPage];
    }
    const firstLoadedPageNumber = Object.keys(state.pageCache)
        .map(Number)
        .sort((left, right) => left - right)[0];
    return firstLoadedPageNumber ? state.pageCache[firstLoadedPageNumber] : null;
}

function refreshReaderHeader() {
    if (!state.currentPaper) {
        els.paperTitle.textContent = "还没有打开论文";
        els.paperMetaLine.textContent = "中间列默认以连续阅读为主，并保留缩放与跳页能力。";
        els.guideTitle.textContent = "未打开论文";
        els.chatContextBadge.textContent = "未连接论文";
        els.pageSelect.disabled = true;
        els.prevPageButton.disabled = true;
        els.nextPageButton.disabled = true;
        updateZoomControls();
        return;
    }

    const modeLabel = state.reader.mode === "continuous" ? "连续阅读" : "单页";
    const zoomLabel = state.reader.zoomMode === "fit"
        ? `适应宽度 ${Math.round(getActiveScale() * 100)}%`
        : `缩放 ${Math.round(getActiveScale() * 100)}%`;

    els.paperTitle.textContent = state.currentPaper.title;
    els.guideTitle.textContent = state.currentPaper.reading_guide?.paper_title || state.currentPaper.title;
    els.paperMetaLine.textContent = `${state.currentPaper.page_count || 0} 页 · ${state.currentPaper.source_label || state.currentPaper.filename} · ${modeLabel} · ${zoomLabel} · chat 以全文上下文为主`;
    els.chatContextBadge.textContent = `全文上下文 · 第 ${state.currentPage} 页`;
    els.pageSelect.disabled = false;
    els.pageSelect.value = String(state.currentPage);
    els.prevPageButton.disabled = state.currentPage <= 1;
    els.nextPageButton.disabled = state.currentPage >= state.currentPaper.page_count;
    updateZoomControls();
}

function updateViewerStatus() {
    if (!state.currentPaper) {
        els.viewerStatus.textContent = "当前版本默认连续阅读，selection action 只在你手动选择后触发。";
        return;
    }

    const loadedPageCount = Object.keys(state.pageCache).length;
    if (state.reader.mode === "continuous" && loadedPageCount < state.currentPaper.page_count) {
        const contextHint = state.currentPaper.cache_state === "warming"
            ? "全文上下文仍在后台准备。"
            : "其余页面会随着滚动按需加载。";
        els.viewerStatus.textContent = `连续阅读已可开始：已准备 ${loadedPageCount}/${state.currentPaper.page_count} 页，${contextHint}`;
        return;
    }

    const currentPageData = state.pageCache[state.currentPage];
    if (currentPageData && !currentPageData.has_text_layer) {
        els.viewerStatus.textContent = "这一页没有可提取的文字层，所以当前页无法触发 selection action。";
        return;
    }

    if (state.currentPaper.cache_state === "warming") {
        els.viewerStatus.textContent = "PDF 已可正常阅读；全文上下文仍在后台准备，你可以先读再问。";
        return;
    }

    if (state.reader.mode === "continuous") {
        els.viewerStatus.textContent = "默认连续阅读已开启；左栏和右栏各自滚动，选中文本后才会弹出解释 / 翻译。";
        return;
    }

    els.viewerStatus.textContent = "当前是单页模式；可继续缩放或切回连续阅读，selection action 仍然需要你手动点击。";
}

function handleViewerScroll() {
    hideSelectionPopover();
    scheduleVisiblePageRenders();
}

function handleWindowResize() {
    applyWorkspaceLayout();
    syncViewerScale();
    hideSelectionPopover();
}

function handleSelectionChange() {
    const selection = window.getSelection();
    const text = selection?.toString().trim();
    if (!text || !selection.anchorNode || !els.viewerPages.contains(toElement(selection.anchorNode))) {
        state.selectedText = "";
        state.selectedRegion = null;
        hideSelectionPopover();
        return;
    }

    const range = selection.rangeCount ? selection.getRangeAt(0) : null;
    if (!range) {
        state.selectedText = "";
        state.selectedRegion = null;
        hideSelectionPopover();
        return;
    }

    const rect = range.getBoundingClientRect();
    if (!rect || (!rect.width && !rect.height)) {
        state.selectedText = "";
        state.selectedRegion = null;
        hideSelectionPopover();
        return;
    }

    const selectionRoot = toElement(range.commonAncestorContainer) || toElement(selection.anchorNode);
    const pageNode = selectionRoot?.closest(".paper-page");
    if (!pageNode) {
        state.selectedText = "";
        state.selectedRegion = null;
        hideSelectionPopover();
        return;
    }

    state.selectedText = text.slice(0, 5000);
    state.selectedPage = Number(pageNode.dataset.pageNumber || state.currentPage);
    state.selectedRegion = buildSelectionRegion(pageNode, range, state.selectedPage);
    showSelectionPopover(rect);
}

function buildSelectionRegion(pageNode, range, pageNumber) {
    const page = state.pageCache[pageNumber];
    const stage = pageNode?.querySelector(".page-stage");
    if (!page || !stage) {
        return null;
    }

    const scale = getScaleForPage(page);
    const stageRect = stage.getBoundingClientRect();
    if (!scale || !stageRect.width || !stageRect.height) {
        return null;
    }

    const rects = [];
    for (const clientRect of Array.from(range.getClientRects())) {
        const nextRect = normalizeSelectionClientRect(clientRect, stageRect, scale);
        if (nextRect) {
            rects.push(nextRect);
        }
    }

    if (!rects.length) {
        const fallbackRect = normalizeSelectionClientRect(range.getBoundingClientRect(), stageRect, scale);
        if (fallbackRect) {
            rects.push(fallbackRect);
        }
    }

    if (!rects.length) {
        return null;
    }

    const bounds = rects.reduce((current, rect) => {
        if (!current) {
            return { ...rect };
        }
        const left = Math.min(current.x, rect.x);
        const top = Math.min(current.y, rect.y);
        const right = Math.max(current.x + current.width, rect.x + rect.width);
        const bottom = Math.max(current.y + current.height, rect.y + rect.height);
        return {
            x: roundSelectionValue(left),
            y: roundSelectionValue(top),
            width: roundSelectionValue(right - left),
            height: roundSelectionValue(bottom - top),
        };
    }, null);

    return {
        page_number: pageNumber,
        page_width: roundSelectionValue(page.width),
        page_height: roundSelectionValue(page.height),
        bounds,
        rects,
    };
}

function normalizeSelectionClientRect(rect, stageRect, scale) {
    if (!rect || !rect.width || !rect.height) {
        return null;
    }

    const left = Math.max(rect.left, stageRect.left);
    const top = Math.max(rect.top, stageRect.top);
    const right = Math.min(rect.right, stageRect.right);
    const bottom = Math.min(rect.bottom, stageRect.bottom);
    if (right <= left || bottom <= top) {
        return null;
    }

    return {
        x: roundSelectionValue((left - stageRect.left) / scale),
        y: roundSelectionValue((top - stageRect.top) / scale),
        width: roundSelectionValue((right - left) / scale),
        height: roundSelectionValue((bottom - top) / scale),
    };
}

function roundSelectionValue(value) {
    return Math.round(Number(value || 0) * 1000) / 1000;
}

function showSelectionPopover(rect) {
    const left = Math.max(12, Math.min(window.innerWidth - 180, rect.left + rect.width / 2 - 80));
    const top = Math.max(12, rect.top - 52);
    els.selectionPopover.style.left = `${left}px`;
    els.selectionPopover.style.top = `${top}px`;
    els.selectionPopover.classList.remove("hidden");
}

function hideSelectionPopover() {
    els.selectionPopover.classList.add("hidden");
}

function handleDocumentMouseDown(event) {
    if (els.selectionPopover.contains(event.target)) {
        return;
    }
    if (els.viewerPages.contains(event.target)) {
        return;
    }
    hideSelectionPopover();
}

async function generateReadingGuide() {
    if (!state.currentPaper) {
        return;
    }

    setBusy(els.generateGuideButton, true, "生成中...");
    state.guideToastPending = true;

    try {
        const data = await api(`/api/papers/${state.currentPaper.id}/reading-guide`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(requestConfigBody()),
        });

        applyCurrentPaperPayload(data.paper);
        state.guideProgress = normalizeGuideProgress(data.status || state.currentPaper?.guide_progress);
        if (data.reading_guide && state.currentPaper) {
            state.currentPaper.reading_guide = data.reading_guide;
        }

        renderGuide(state.currentPaper?.reading_guide || null);
        refreshReaderHeader();

        if (data.reading_guide || state.guideProgress?.state === "ready") {
            state.guideToastPending = false;
            showToast("阅读导图已生成。");
        }
        else if (isGuideProgressRunning(state.guideProgress) && state.currentPaper) {
            startGuidePolling(state.currentPaper.id);
        }
        else if (state.guideProgress?.state === "failed") {
            state.guideToastPending = false;
            showToast(state.guideProgress.error || "生成阅读导图失败。");
        }
    }
    catch (error) {
        state.guideToastPending = false;
        els.guideStatus.textContent = "失败";
        showToast(error.message);
    }
    finally {
        updateActionAvailability();
    }
}

function renderGuide(guide) {
    const progress = normalizeGuideProgress(state.guideProgress || state.currentPaper?.guide_progress);
    state.guideProgress = progress;

    if (!state.currentPaper) {
        els.guideStatus.textContent = "待打开";
        els.guidePanel.className = "guide-panel empty-state";
        els.guidePanel.textContent = "先打开一篇论文，再生成整篇阅读导图。";
        return;
    }

    if (progress?.state === "running") {
        els.guideStatus.textContent = progress.badge || "生成中";
        els.guidePanel.className = "guide-panel";
        els.guidePanel.innerHTML = renderGuideProgress(progress);
        return;
    }

    if (!guide) {
        if (progress?.state === "failed") {
            els.guideStatus.textContent = progress.badge || "失败";
            els.guidePanel.className = "guide-panel";
            els.guidePanel.innerHTML = renderGuideFailure(progress, false);
            return;
        }

        els.guideStatus.textContent = progress?.badge || "待生成";
        els.guidePanel.className = "guide-panel empty-state";
        if (progress?.state === "stale") {
            els.guidePanel.textContent = "论文内容已更新，建议重新生成阅读导图。";
        }
        else {
            els.guidePanel.textContent = "点击“生成阅读导图”后，这里会显示整篇论文的一句话总结、背景、问题、创新、方法、结果、局限和建议阅读顺序。";
        }
        return;
    }

    const blocks = [];
    if (progress?.state === "failed") {
        els.guideStatus.textContent = progress.badge || "失败";
        blocks.push(renderGuideFailure(progress, true));
    }
    else if (progress?.state === "stale") {
        els.guideStatus.textContent = progress.badge || "待更新";
        blocks.push(renderGuideStaleNotice(progress));
    }
    else {
        els.guideStatus.textContent = guide.model ? `已生成 · ${guide.model}` : (progress?.badge || "已生成");
    }

    els.guidePanel.className = "guide-panel";
    blocks.push(
        `
            <section class="guide-intro">
                <strong>${escapeHtml(guide.paper_title || state.currentPaper.title)}</strong>
                <div class="rich-text guide-rich-text">${renderMarkdownContent(guide.one_sentence || "暂无一句话总结。")}</div>
            </section>
        `,
        renderGuideGroup("研究背景", guide.background),
        renderGuideGroup("核心问题", guide.problem),
        renderGuideGroup("创新点", guide.innovations),
        renderGuideGroup("方法", guide.method),
        renderGuideGroup("结果", guide.results),
        renderGuideGroup("局限", guide.limitations),
        renderGuideGroup("建议阅读顺序", guide.reading_guide),
        renderGuideSections(guide.sections),
    );
    els.guidePanel.innerHTML = blocks.join("");
}

function renderGuideGroup(title, items) {
    const cleanItems = (items || []).filter(Boolean);
    if (!cleanItems.length) {
        return "";
    }
    return `
        <section class="guide-group">
            <h3>${escapeHtml(title)}</h3>
            <div class="rich-text guide-rich-text">${renderMarkdownList(cleanItems)}</div>
        </section>
    `;
}

function renderGuideSections(sections) {
    const cleanSections = (sections || []).filter(Boolean);
    if (!cleanSections.length) {
        return "";
    }
    const sectionBullets = cleanSections.map((section) => {
        const pageHint = section.page_hint ? ` (约第 ${section.page_hint} 页)` : "";
        const title = escapeMarkdownText(section.title || "");
        const summary = String(section.summary || "").trim();
        return `**${title}${escapeMarkdownText(pageHint)}**${summary ? `: ${summary}` : ""}`;
    });
    return `
        <section class="guide-group">
            <h3>重要内容单元</h3>
            <div class="rich-text guide-rich-text">${renderMarkdownList(sectionBullets)}</div>
        </section>
    `;
}

function renderGuideProgress(progress) {
    const segments = (progress.steps || []).map((step) => `
        <span class="guide-progress-segment is-${escapeHtml(step.state)}" aria-hidden="true"></span>
    `).join("");
    const steps = (progress.steps || []).map((step) => `
        <li class="guide-stage-item is-${escapeHtml(step.state)}">
            <span class="guide-stage-dot" aria-hidden="true"></span>
            <div class="guide-stage-meta">
                <strong>${escapeHtml(step.label || step.id)}</strong>
                <span>${escapeHtml(describeGuideStepState(step.state))}</span>
            </div>
        </li>
    `).join("");

    return `
        <section class="guide-progress-card">
            <div class="guide-progress-head">
                <strong>阅读导图生成中</strong>
                <span>${escapeHtml(progress.stage_label || progress.badge || "")}</span>
            </div>
            <div class="guide-progress-track" aria-hidden="true">${segments}</div>
            <p class="guide-progress-message">${escapeHtml(progress.message || "正在准备阅读导图。")}</p>
            <ol class="guide-stage-list">${steps}</ol>
        </section>
    `;
}

function renderGuideFailure(progress, inline) {
    const title = inline
        ? "本次重新生成失败"
        : "阅读导图生成失败";
    const hint = inline
        ? "下方保留了上一份导图，你可以稍后再试一次。"
        : "可以再次点击“生成阅读导图”重试。";
    return `
        <section class="guide-progress-card guide-progress-card--failure">
            <div class="guide-progress-head">
                <strong>${title}</strong>
                <span>${escapeHtml(progress.stage_label || progress.badge || "")}</span>
            </div>
            <p class="guide-progress-message">${escapeHtml(progress.error || progress.message || "本次生成未完成。")}</p>
            <p class="guide-progress-note">${hint}</p>
        </section>
    `;
}

function renderGuideStaleNotice(progress) {
    return `
        <section class="guide-progress-card guide-progress-card--subtle">
            <div class="guide-progress-head">
                <strong>导图需要更新</strong>
                <span>${escapeHtml(progress.badge || "待更新")}</span>
            </div>
            <p class="guide-progress-message">${escapeHtml(progress.message || "论文内容已更新，建议重新生成阅读导图。")}</p>
        </section>
    `;
}

function describeGuideStepState(stepState) {
    return {
        pending: "待开始",
        current: "进行中",
        complete: "已完成",
        failed: "失败",
    }[stepState] || "待开始";
}

async function loadPdfJs() {
    if (state.pdf.lib) {
        return state.pdf.lib;
    }
    if (!state.pdf.modulePromise) {
        state.pdf.modulePromise = import(PDFJS_MODULE_URL)
            .then((module) => {
                module.GlobalWorkerOptions.workerSrc = PDFJS_WORKER_URL;
                state.pdf.lib = module;
                return module;
            })
            .catch((error) => {
                state.pdf.modulePromise = null;
                throw error;
            });
    }
    return state.pdf.modulePromise;
}

async function ensurePdfDocumentReady() {
    const pdfUrl = state.currentPaper?.pdf_url;
    if (!pdfUrl) {
        return null;
    }

    const resolvedUrl = new URL(pdfUrl, window.location.origin).toString();
    if (state.pdf.document && state.pdf.documentUrl === resolvedUrl) {
        return state.pdf.document;
    }
    if (state.pdf.documentPromise && state.pdf.documentUrl === resolvedUrl) {
        return state.pdf.documentPromise;
    }

    resetPdfDocument();
    const pdfjs = await loadPdfJs();
    const loadingTask = pdfjs.getDocument({
        url: resolvedUrl,
        cMapUrl: `${PDFJS_BASE}cmaps/`,
        cMapPacked: true,
        iccUrl: `${PDFJS_BASE}iccs/`,
        standardFontDataUrl: `${PDFJS_BASE}standard_fonts/`,
        wasmUrl: `${PDFJS_BASE}wasm/`,
    });

    state.pdf.documentUrl = resolvedUrl;
    state.pdf.loadingTask = loadingTask;
    state.pdf.documentPromise = loadingTask.promise
        .then((documentHandle) => {
            if (state.pdf.documentUrl !== resolvedUrl) {
                documentHandle.destroy();
                throw new Error("PDF document switched while loading.");
            }
            state.pdf.loadingTask = null;
            state.pdf.document = documentHandle;
            return documentHandle;
        })
        .catch((error) => {
            if (state.pdf.documentUrl === resolvedUrl) {
                state.pdf.loadingTask = null;
                state.pdf.documentPromise = null;
                state.pdf.document = null;
                state.pdf.documentUrl = "";
            }
            throw error;
        });
    return state.pdf.documentPromise;
}

function resetPdfDocument() {
    if (state.pdf.renderFrame) {
        cancelAnimationFrame(state.pdf.renderFrame);
        state.pdf.renderFrame = 0;
    }
    for (const task of state.pdf.activeTasks.values()) {
        try {
            task.cancel();
        }
        catch (_error) {
            // Ignore cancellation races while switching papers or zoom levels.
        }
    }
    state.pdf.activeTasks.clear();
    if (state.pdf.loadingTask) {
        try {
            state.pdf.loadingTask.destroy();
        }
        catch (_error) {
            // Ignore destroy races.
        }
    }
    if (state.pdf.document) {
        try {
            state.pdf.document.destroy();
        }
        catch (_error) {
            // Ignore destroy races.
        }
    }
    state.pdf.documentPromise = null;
    state.pdf.loadingTask = null;
    state.pdf.document = null;
    state.pdf.documentUrl = "";
    state.pdf.renderGeneration += 1;
}

function scheduleVisiblePageRenders() {
    if (!state.currentPaper || !els.viewerScrollViewport || els.viewerScrollViewport.classList.contains("hidden")) {
        return;
    }
    if (state.pdf.renderFrame) {
        return;
    }
    state.pdf.renderFrame = requestAnimationFrame(() => {
        state.pdf.renderFrame = 0;
        void renderVisiblePages();
    });
}

async function renderVisiblePages() {
    if (!state.currentPaper) {
        return;
    }

    const pageNumbers = collectRenderablePageNumbers();
    try {
        await ensurePagesLoaded(pageNumbers, { silent: true });
    }
    catch (error) {
        els.viewerStatus.textContent = error.message;
        return;
    }

    let pdfDocument;
    try {
        pdfDocument = await ensurePdfDocumentReady();
    }
    catch (error) {
        els.viewerStatus.textContent = error.message;
        return;
    }
    if (!pdfDocument) {
        return;
    }

    for (const pageNumber of pageNumbers) {
        try {
            await ensurePdfPageRendered(pageNumber, pdfDocument);
        }
        catch (error) {
            els.viewerStatus.textContent = error.message;
            break;
        }
    }
}

function collectRenderablePageNumbers() {
    if (!state.currentPaper) {
        return [];
    }
    if (state.reader.mode === "single") {
        return [state.currentPage];
    }

    const viewportRect = els.viewerScrollViewport.getBoundingClientRect();
    const candidates = [];
    for (const pageNode of els.viewerPages.querySelectorAll(".paper-page")) {
        const rect = pageNode.getBoundingClientRect();
        if (rect.bottom < viewportRect.top - viewportRect.height * 0.35 || rect.top > viewportRect.bottom + viewportRect.height * 0.35) {
            continue;
        }
        const pageNumber = Number(pageNode.dataset.pageNumber || 0);
        if (!pageNumber) {
            continue;
        }
        const intersectsViewport = rect.bottom > viewportRect.top && rect.top < viewportRect.bottom;
        const viewportDistance = intersectsViewport
            ? 0
            : Math.min(Math.abs(rect.top - viewportRect.bottom), Math.abs(rect.bottom - viewportRect.top));
        candidates.push({
            pageNumber,
            intersectsViewport,
            viewportDistance,
            currentDistance: Math.abs(pageNumber - state.currentPage),
        });
    }

    const ordered = [];
    if (state.currentPage) {
        ordered.push(state.currentPage);
    }
    candidates
        .sort((left, right) => (
            Number(right.intersectsViewport) - Number(left.intersectsViewport)
            || left.viewportDistance - right.viewportDistance
            || left.currentDistance - right.currentDistance
            || left.pageNumber - right.pageNumber
        ))
        .forEach((entry) => ordered.push(entry.pageNumber));

    for (const pageNumber of [state.currentPage + 1, state.currentPage - 1, state.currentPage + 2]) {
        if (pageNumber >= 1 && pageNumber <= state.currentPaper.page_count) {
            ordered.push(pageNumber);
        }
    }

    const unique = [];
    for (const pageNumber of ordered) {
        if (!pageNumber || unique.includes(pageNumber)) {
            continue;
        }
        unique.push(pageNumber);
        if (unique.length >= MAX_CONTINUOUS_RENDER_PAGES) {
            break;
        }
    }
    return unique;
}

async function ensurePdfPageRendered(pageNumber, pdfDocument = state.pdf.document) {
    const page = state.pageCache[pageNumber];
    const pageNode = els.viewerPages.querySelector(`.paper-page[data-page-number="${pageNumber}"]`);
    const canvas = pageNode?.querySelector(".page-canvas");
    if (!page || !pageNode || !canvas || !pdfDocument) {
        return;
    }

    const cssScale = getScaleForPage(page);
    const outputScale = Math.max(window.devicePixelRatio || 1, 1);
    const renderKey = `${cssScale.toFixed(3)}@${outputScale.toFixed(2)}`;
    if (canvas.dataset.renderKey === renderKey) {
        markPageRendered(pageNode);
        return;
    }

    const previousTask = state.pdf.activeTasks.get(pageNumber);
    if (previousTask) {
        try {
            previousTask.cancel();
        }
        catch (_error) {
            // Ignore cancellation races when a page is re-rendered quickly.
        }
    }

    if (!canvas.dataset.renderKey) {
        markPageLoading(pageNode);
    }

    const generation = state.pdf.renderGeneration;
    const pdfPage = await pdfDocument.getPage(pageNumber);
    if (generation !== state.pdf.renderGeneration) {
        pdfPage.cleanup();
        return;
    }

    const cssViewport = pdfPage.getViewport({ scale: cssScale });
    const renderViewport = pdfPage.getViewport({ scale: cssScale * outputScale });
    const context = canvas.getContext("2d", { alpha: false });
    if (!context) {
        pdfPage.cleanup();
        return;
    }

    const stagingCanvas = document.createElement("canvas");
    stagingCanvas.width = Math.max(1, Math.ceil(renderViewport.width));
    stagingCanvas.height = Math.max(1, Math.ceil(renderViewport.height));
    const stagingContext = stagingCanvas.getContext("2d", { alpha: false });
    if (!stagingContext) {
        pdfPage.cleanup();
        return;
    }
    stagingContext.fillStyle = "#ffffff";
    stagingContext.fillRect(0, 0, stagingCanvas.width, stagingCanvas.height);

    const renderTask = pdfPage.render({
        canvasContext: stagingContext,
        viewport: renderViewport,
    });
    state.pdf.activeTasks.set(pageNumber, renderTask);

    try {
        await renderTask.promise;
        if (generation === state.pdf.renderGeneration) {
            canvas.width = stagingCanvas.width;
            canvas.height = stagingCanvas.height;
            canvas.style.width = `${cssViewport.width}px`;
            canvas.style.height = `${cssViewport.height}px`;
            context.clearRect(0, 0, canvas.width, canvas.height);
            context.drawImage(stagingCanvas, 0, 0);
            canvas.dataset.renderKey = renderKey;
            markPageRendered(pageNode);
        }
    }
    catch (error) {
        if (error?.name !== "RenderingCancelledException") {
            if (!canvas.dataset.renderKey) {
                markPageLoading(pageNode);
            }
            throw error;
        }
    }
    finally {
        if (state.pdf.activeTasks.get(pageNumber) === renderTask) {
            state.pdf.activeTasks.delete(pageNumber);
        }
        pdfPage.cleanup();
    }
}

function markPageLoading(pageNode) {
    pageNode.classList.add("is-loading");
    pageNode.classList.remove("is-rendered");
}

function markPageRendered(pageNode) {
    pageNode.classList.remove("is-loading");
    pageNode.classList.add("is-rendered");
}

async function sendChatMessage() {
    if (!state.currentPaper) {
        return;
    }
    const content = els.chatInput.value.trim();
    if (!content) {
        return;
    }

    state.chatMessages.push({
        role: "user",
        title: `第 ${state.currentPage} 页提问`,
        content,
        meta: "全文上下文聊天",
    });
    els.chatInput.value = "";
    renderChat();
    setBusy(els.chatSendButton, true, "发送中...");
    try {
        const data = await api(`/api/papers/${state.currentPaper.id}/chat`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                ...requestConfigBody(),
                page: state.currentPage,
                messages: state.chatMessages.map(({ role, content: messageContent }) => ({ role, content: messageContent })),
            }),
        });
        state.chatMessages.push({
            role: "assistant",
            title: "论文助手",
            content: data.text,
            meta: "基于全文导图与相关摘录",
        });
        renderChat();
    }
    catch (error) {
        state.chatMessages.push({
            role: "assistant",
            title: "请求失败",
            content: error.message,
            meta: "bridge 或上下文处理失败",
        });
        renderChat();
        showToast(error.message);
    }
    finally {
        setBusy(els.chatSendButton, false, "发送");
        updateActionAvailability();
    }
}

async function runSelectionAction(mode) {
    if (!state.currentPaper || !state.selectedText) {
        hideSelectionPopover();
        return;
    }

    const targetPage = state.selectedPage || state.currentPage;
    const label = mode === "translate" ? "翻译选中文本" : "解释选中文本";
    const requestText = `${label}：
${state.selectedText}`;
    state.chatMessages.push({
        role: "user",
        title: `${label} · 第 ${targetPage} 页`,
        content: requestText,
        meta: "selection action",
    });
    renderChat();
    hideSelectionPopover();

    try {
        const data = await api(`/api/papers/${state.currentPaper.id}/selection-action`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                ...requestConfigBody(),
                page: targetPage,
                text: state.selectedText,
                mode,
                selection_region: state.selectedRegion,
            }),
        });
        state.chatMessages.push({
            role: "assistant",
            title: mode === "translate" ? "翻译结果" : "解释结果",
            content: data.text,
            meta: "选中文本操作",
            debugCrop: data.debug_crop || null,
            debugCropError: data.debug_crop_error || "",
        });
        renderChat();
    }
    catch (error) {
        state.chatMessages.push({
            role: "assistant",
            title: "操作失败",
            content: error.message,
            meta: "selection action",
        });
        renderChat();
        showToast(error.message);
    }
    finally {
        clearSelection();
    }
}

function renderChat() {
    if (!state.currentPaper) {
        els.chatMessages.className = "chat-messages empty-state";
        els.chatMessages.textContent = "打开论文后，可以直接提问整篇论文。系统会优先使用全文导图和相关页面摘录，而不是只盯当前页。";
        return;
    }

    if (!state.chatMessages.length) {
        els.chatMessages.className = "chat-messages empty-state";
        els.chatMessages.textContent = "可以开始提问了。例如：这篇论文的核心创新是什么？这一页和整篇文章的主线是什么关系？";
        return;
    }

    els.chatMessages.className = "chat-messages";
    els.chatMessages.innerHTML = state.chatMessages.map((message) => `
        <section class="chat-card ${message.role}">
            <p class="meta-line">${escapeHtml(message.role === "user" ? "你" : "AI")} · ${escapeHtml(message.meta || "")}</p>
            <strong>${escapeHtml(message.title || (message.role === "user" ? "问题" : "回答"))}</strong>
            <div class="rich-text chat-rich-text">${renderMarkdownContent(message.content)}</div>
            ${renderSelectionDebugBlock(message)}
        </section>
    `).join("");
    els.chatMessages.scrollTop = els.chatMessages.scrollHeight;
}

function renderSelectionDebugBlock(message) {
    const debugCrop = message.debugCrop;
    const debugCropError = String(message.debugCropError || "").trim();
    if (!debugCrop && !debugCropError) {
        return "";
    }

    const parts = [
        '<div class="selection-debug-block">',
        '<p class="selection-debug-kicker">Selection Crop Debug</p>',
    ];

    if (debugCrop?.image_url) {
        parts.push(`
            <figure class="selection-debug-preview">
                <img src="${escapeHtml(debugCrop.image_url)}" alt="选区裁图调试预览" loading="lazy">
                <figcaption>第 ${escapeHtml(String(debugCrop.page_number || ""))} 页 · 裁图 ${escapeHtml(String(debugCrop.pixel_bounds?.width || "?"))} × ${escapeHtml(String(debugCrop.pixel_bounds?.height || "?"))} px</figcaption>
            </figure>
        `);
    }

    if (debugCropError) {
        parts.push(`<p class="selection-debug-note is-error">裁图调试未生成：${escapeHtml(debugCropError)}</p>`);
    }
    else {
        parts.push('<p class="selection-debug-note">这是当前选区的调试裁图，用于后续 Stage A OCR 路径验证。</p>');
    }

    parts.push('</div>');
    return parts.join("");
}

function clearSelection() {

    state.selectedText = "";
    state.selectedPage = state.currentPage;
    state.selectedRegion = null;
    hideSelectionPopover();
    if (window.getSelection) {
        window.getSelection().removeAllRanges();
    }
}

function updateActionAvailability() {
    const hasPaper = Boolean(state.currentPaper);
    const guideRunning = isGuideProgressRunning(state.guideProgress);
    els.generateGuideButton.disabled = !hasPaper || guideRunning;
    els.generateGuideButton.textContent = guideRunning ? "生成中..." : "生成阅读导图";
    els.chatSendButton.disabled = !hasPaper;
}

function requestConfigBody() {
    persistSettings();
    return {
        bridge_url: state.settings.bridgeUrl,
        model: state.settings.model,
        api_key: state.settings.apiKey,
        reasoning_effort: state.settings.reasoningEffort,
    };
}

function persistSettings() {
    state.settings.bridgeUrl = els.bridgeUrlInput.value.trim() || shell.dataset.defaultBridgeUrl || "http://127.0.0.1:8765/v1";
    state.settings.model = els.modelInput.value.trim() || DEFAULT_MODEL;
    state.settings.reasoningEffort = normalizeReasoningEffort(els.reasoningEffortSelect.value);
    state.settings.apiKey = els.apiKeyInput.value;
    state.settings.libraryPath = els.libraryPathInput.value.trim();

    localStorage.setItem("paperReaderAgent.bridgeUrl", state.settings.bridgeUrl);
    localStorage.setItem("paperReaderAgent.model", state.settings.model);
    localStorage.setItem("paperReaderAgent.reasoningEffort", state.settings.reasoningEffort);
    localStorage.setItem("paperReaderAgent.apiKey", state.settings.apiKey);
    localStorage.setItem("paperReaderAgent.libraryPath", state.settings.libraryPath);
}

function persistReaderPreferences() {
    localStorage.setItem("paperReaderAgent.readerMode", state.reader.mode);
    localStorage.setItem("paperReaderAgent.zoomMode", state.reader.zoomMode);
    localStorage.setItem("paperReaderAgent.zoomScale", String(state.reader.zoomScale));
}

function persistLayoutPreferences() {
    localStorage.setItem("paperReaderAgent.guideWidth", String(Math.round(state.layout.guideWidth)));
    localStorage.setItem("paperReaderAgent.chatWidth", String(Math.round(state.layout.chatWidth)));
}

function normalizeReasoningEffort(value) {
    const effort = String(value || "").trim().toLowerCase();
    if (!effort || effort === "default") {
        return "";
    }
    if (effort === "median") {
        return "medium";
    }
    return effort;
}

function normalizeReaderMode(value) {
    return String(value || "").trim().toLowerCase() === "single" ? "single" : "continuous";
}

function normalizeZoomMode(value) {
    return String(value || "").trim().toLowerCase() === "manual" ? "manual" : "fit";
}

function normalizeZoomScale(value) {
    return clampZoomScale(Number(value || 1));
}

function normalizeSidebarWidth(value, fallback, minimum, maximum) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) {
        return fallback;
    }
    return clampNumber(numeric, minimum, maximum);
}

function clampZoomScale(value) {
    if (!Number.isFinite(value)) {
        return 1;
    }
    return Math.min(4.0, Math.max(0.55, value));
}

function clampNumber(value, minimum, maximum) {
    return Math.min(maximum, Math.max(minimum, value));
}

function isDesktopWorkspace() {
    return window.innerWidth > 1500;
}

function listAllPageNumbers() {
    if (!state.currentPaper) {
        return [];
    }
    return Array.from({ length: state.currentPaper.page_count }, (_value, index) => index + 1);
}

function toElement(node) {
    if (!node) {
        return null;
    }
    return node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement;
}

function setBusy(button, busy, label) {
    button.disabled = busy;
    button.textContent = label;
}

async function api(url, options = {}) {
    const response = await fetch(url, options);
    const isJson = response.headers.get("content-type")?.includes("application/json");
    const payload = isJson ? await response.json() : {};
    if (!response.ok) {
        throw new Error(payload.message || `请求失败 (${response.status})`);
    }
    return payload;
}

function showToast(message) {
    els.toast.textContent = message;
    els.toast.classList.remove("hidden");
    clearTimeout(showToast.timer);
    showToast.timer = setTimeout(() => {
        els.toast.classList.add("hidden");
    }, 3200);
}

function getMarkdownRenderer() {
    if (typeof window.markdownit !== "function") {
        return null;
    }
    if (!getMarkdownRenderer.instance) {
        getMarkdownRenderer.instance = window.markdownit({
            html: false,
            linkify: true,
            typographer: false,
            breaks: false,
        });
    }
    return getMarkdownRenderer.instance;
}

function renderMarkdownContent(source) {
    const text = normalizeMarkdownSource(source);
    if (!text) {
        return "";
    }

    const protectedDisplayMath = protectDisplayMathBlocks(text);
    const protectedInlineMath = protectInlineMathSpans(protectedDisplayMath.text);
    const renderer = getMarkdownRenderer();
    if (!renderer) {
        return renderPlainTextHtml(text);
    }

    const container = document.createElement("div");
    try {
        container.innerHTML = renderer.render(protectedInlineMath.text);
        restoreProtectedInlineMath(container, protectedInlineMath.blocks);
        restoreProtectedDisplayMath(container, protectedDisplayMath.blocks);
        normalizeRichLinks(container);
        applyMathRendering(container);
        if (!container.innerHTML.trim()) {
            return renderPlainTextHtml(text);
        }
        return container.innerHTML;
    }
    catch (error) {
        console.warn("Markdown render fallback", error);
        return renderPlainTextHtml(text);
    }
}

function renderMarkdownList(items) {
    const cleanItems = (items || []).map((item) => String(item ?? "").trim()).filter(Boolean);
    if (!cleanItems.length) {
        return "";
    }

    if (!getMarkdownRenderer()) {
        return `<ul>${cleanItems.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;
    }

    const markdown = cleanItems.map((item) => `- ${item}`).join("\n");
    return renderMarkdownContent(markdown);
}

function normalizeMarkdownSource(source) {
    return String(source ?? "")
        .replaceAll("\r\n", "\n")
        .trim();
}

function protectDisplayMathBlocks(text) {
    const blocks = [];
    const protectedText = String(text ?? "").replace(/(\$\$[\s\S]+?\$\$|\\\[[\s\S]+?\\\])/g, (match) => {
        const token = `PRA_DISPLAY_MATH_BLOCK_${blocks.length}_TOKEN`;
        blocks.push({ token, math: match });
        return token;
    });
    return { text: protectedText, blocks };
}

function restoreProtectedDisplayMath(container, blocks) {
    if (!container || !blocks?.length) {
        return;
    }

    let html = container.innerHTML;
    for (const block of blocks) {
        const wrappedTokenPattern = new RegExp(`<p>\s*${block.token}\s*</p>`, "g");
        html = html.replace(wrappedTokenPattern, () => block.math);
        html = html.replaceAll(block.token, block.math);
    }
    container.innerHTML = html;
}

function protectInlineMathSpans(text) {
    const blocks = [];
    let protectedText = String(text ?? "");

    protectedText = protectedText.replace(/\\\((.+?)\\\)/g, (match, content) => {
        return maybeProtectInlineMath(match, content, blocks);
    });

    protectedText = protectedText.replace(/\$([^\$\n]+)\$/g, (match, content) => {
        return maybeProtectInlineMath(match, content, blocks);
    });

    return { text: protectedText, blocks };
}

function maybeProtectInlineMath(match, content, blocks) {
    if (!looksLikeMathInlineSpan(content)) {
        return match;
    }

    const token = `PRA_INLINE_MATH_BLOCK_${blocks.length}_TOKEN`;
    blocks.push({ token, math: match });
    return token;
}

function looksLikeMathInlineSpan(content) {
    const value = String(content ?? "").trim();
    if (!value || value.length > 320) {
        return false;
    }

    if (/[\\_^{}]/.test(value)) {
        return true;
    }

    if (/[=<>|]/.test(value) && /[A-Za-z]/.test(value)) {
        return true;
    }

    if (/\\(?:frac|hat|mathbb|mathcal|mathrm|left|right|le|ge|lambda|nu|pi|epsilon|kappa|sigma|argmin|argmax|infty)/i.test(value)) {
        return true;
    }

    return false;
}

function restoreProtectedInlineMath(container, blocks) {
    if (!container || !blocks?.length) {
        return;
    }

    let html = container.innerHTML;
    for (const block of blocks) {
        html = html.replaceAll(block.token, block.math);
    }
    container.innerHTML = html;
}

function renderPlainTextHtml(text) {
    const blocks = normalizeMarkdownSource(text)
        .split(/\n{2,}/)
        .map((block) => block.trim())
        .filter(Boolean);
    return blocks.map((block) => `<p>${escapeHtml(block).replaceAll("\n", "<br>")}</p>`).join("");
}

function normalizeRichLinks(container) {
    for (const link of container.querySelectorAll("a[href]")) {
        link.target = "_blank";
        link.rel = "noreferrer noopener";
    }
}

function applyMathRendering(container) {
    if (typeof window.renderMathInElement !== "function" || typeof window.katex === "undefined") {
        return;
    }

    window.renderMathInElement(container, {
        delimiters: RICH_TEXT_MATH_DELIMITERS,
        ignoredTags: ["script", "noscript", "style", "textarea", "pre", "code", "option"],
        throwOnError: false,
        strict: "ignore",
        trust: false,
    });
}

function escapeMarkdownText(value) {
    return String(value ?? "")
        .replaceAll("\\", "\\\\")
        .replace(/([*_`~\[\]<>])/g, "\\$1");
}

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
}

function escapeAttribute(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll('"', "&quot;");
}

init();




