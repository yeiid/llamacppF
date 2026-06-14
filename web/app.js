/* ============================================================
   FRONTEND LOGIC — LLAMA.CPP CLUSTER DASHBOARD
   ============================================================ */

document.addEventListener("DOMContentLoaded", () => {
    // --- STATED STATE ---
    let state = {
        localIp: "127.0.0.1",
        subnet: "",
        llamaPort: 8080,
        rpcPort: 50052,
        isServerRunning: false,
        isWorkerRunning: false,
        activeModel: null,
        models: [],
        nodes: [],
        chatMessages: [],
        activeTab: "tab-chat"
    };

    // --- TIMERS ---
    let statusInterval = null;
    let logsInterval = null;

    // --- HTML ELEMENTS ---
    // Status Indicators
    const maestroDot = document.getElementById("status-maestro-dot");
    const maestroText = document.getElementById("status-maestro-text");
    const workerDot = document.getElementById("status-worker-dot");
    const workerText = document.getElementById("status-worker-text");
    const infoLocalIp = document.getElementById("info-local-ip");
    const infoApiPort = document.getElementById("info-api-port");
    const infoActiveModel = document.getElementById("info-active-model");
    const infoSubnet = document.getElementById("info-subnet");
    
    // Controls
    const selectServerModel = document.getElementById("select-server-model");
    const btnStartServer = document.getElementById("btn-start-server");
    const btnStartWorker = document.getElementById("btn-start-worker");
    const btnStopAll = document.getElementById("btn-stop-all");
    const btnRefreshNodes = document.getElementById("btn-refresh-nodes");
    const nodesListUl = document.getElementById("nodes-list-ul");
    
    // Tab Navigation
    const tabBtns = document.querySelectorAll(".tab-btn");
    const tabPanes = document.querySelectorAll(".tab-pane");
    
    // Chat Playground
    const chatMessagesContainer = document.getElementById("chat-messages-container");
    const chatInputTextarea = document.getElementById("chat-input-textarea");
    const btnSendMessage = document.getElementById("btn-send-message");
    const btnClearChat = document.getElementById("btn-clear-chat");
    const chatModelIndicator = document.getElementById("chat-model-indicator");
    const selectPersona = document.getElementById("select-persona");
    const rangeTemperature = document.getElementById("range-temperature");
    const valTemperature = document.getElementById("val-temperature");
    const rangeMaxTokens = document.getElementById("range-max-tokens");
    const valMaxTokens = document.getElementById("val-max-tokens");
    const textareaSystemPrompt = document.getElementById("textarea-system-prompt");
    const paramsApiStatusInfo = document.getElementById("params-api-status-info");
    
    // Benchmark
    const benchmarkPrompt = document.getElementById("benchmark-prompt");
    const benchmarkTokens = document.getElementById("benchmark-tokens");
    const btnRunBenchmark = document.getElementById("btn-run-benchmark");
    const benchValTps = document.getElementById("bench-val-tps");
    const benchValFirstToken = document.getElementById("bench-val-first-token");
    const benchValTotalTime = document.getElementById("bench-val-total-time");
    const benchValCount = document.getElementById("bench-val-count");
    const benchmarkOutputPreviewText = document.getElementById("benchmark-output-preview-text");
    
    // Logs / Diag
    const selectLogType = document.getElementById("select-log-type");
    const btnRefreshLogs = document.getElementById("btn-refresh-logs");
    const btnCopyLogs = document.getElementById("btn-copy-logs");
    const terminalPre = document.getElementById("terminal-pre");
    const btnRunDiag = document.getElementById("btn-run-diag");
    const diagOutputBox = document.getElementById("diag-output-box");
    
    // Settings
    const inputThreads = document.getElementById("input-threads");
    const inputCtxSize = document.getElementById("input-ctx-size");
    const inputBatchSize = document.getElementById("input-batch-size");
    const inputLlamaPort = document.getElementById("input-llama-port");
    const inputRpcPort = document.getElementById("input-rpc-port");
    const inputSubnet = document.getElementById("input-subnet");
    const btnSaveSettings = document.getElementById("btn-save-settings");
    const settingsStatusMsg = document.getElementById("settings-status-msg");

    // Monitoring Elements
    const monCurrentCpu = document.getElementById("mon-current-cpu");
    const monCurrentRam = document.getElementById("mon-current-ram");
    const monCurrentTemp = document.getElementById("mon-current-temp");
    const monCurrentUptime = document.getElementById("mon-current-uptime");
    const alertBanner = document.getElementById("alert-banner");
    const alertBannerText = document.getElementById("alert-banner-text");
    const btnDismissAlert = document.getElementById("btn-dismiss-alert");
    const toggleAlerts = document.getElementById("toggle-alerts");
    const thresholdCpu = document.getElementById("threshold-cpu");
    const thresholdRam = document.getElementById("threshold-ram");
    const thresholdTemp = document.getElementById("threshold-temp");
    const btnSaveAlerts = document.getElementById("btn-save-alerts");

    // Model Browser Elements
    const btnOpenModels = document.getElementById("btn-open-models");
    const modalModels = document.getElementById("modal-models");
    const btnCloseModels = document.getElementById("btn-close-models");
    const modalRamInfo = document.getElementById("modal-ram-info");
    const modelsCatalogList = document.getElementById("models-catalog-list");
    const downloadActiveIndicator = document.getElementById("download-active-indicator");
    const downloadActiveText = document.getElementById("download-active-text");
    const filterBtns = document.querySelectorAll(".filter-btn");
    let currentCatalog = [];
    let currentFilter = "all";

    // Delete Confirm Modal Elements
    const modalConfirmDelete = document.getElementById("modal-confirm-delete");
    const btnCloseConfirmDelete = document.getElementById("btn-close-confirm-delete");
    const btnCancelDelete = document.getElementById("btn-cancel-delete");
    const btnConfirmDelete = document.getElementById("btn-confirm-delete");
    const deleteModelName = document.getElementById("delete-model-name");
    let modelToDelete = null;

    // --- PERSONA TEMPLATES ---
    const personas = {
        assistant: "Eres un asistente de inteligencia artificial útil, inteligente y amigable. Responde siempre de forma clara, precisa y en español, a menos que se te indique lo contrario.",
        coder: "Eres un programador experto en desarrollo de software. Tu objetivo es proporcionar explicaciones técnicas detalladas y soluciones de código limpias, eficientes y seguras. Comenta los aspectos críticos del código.",
        translator: "Eres un traductor profesional experto. Traduce cualquier texto que te envíe el usuario. Si está en inglés, tradúcelo al español de forma natural. Si está en español, tradúcelo al inglés. No añadas explicaciones ni introducciones, solo la traducción limpia.",
        writer: "Eres un escritor creativo experimentado, especializado en narrativa y poesía. Crea respuestas ricas literariamente, descriptivas y emotivas. Usa un lenguaje evocador.",
        concise: "Eres un asistente analítico ultra preciso. Tu objetivo es responder en la menor cantidad de palabras posible, usando listas de viñetas si es necesario. Ve directo al grano sin introducciones ni saludos."
    };

    // --- CHART INSTANCES ---
    let charts = {};
    let monitoringInterval = null;
    let lastAlertDismiss = 0;

    const chartDefaults = {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 300 },
        plugins: {
            legend: { display: false },
            tooltip: {
                backgroundColor: 'rgba(8, 7, 11, 0.9)',
                titleColor: '#f1f5f9',
                bodyColor: '#94a3b8',
                borderColor: 'rgba(139, 92, 246, 0.3)',
                borderWidth: 1,
                padding: 10,
                displayColors: true,
                intersect: false,
                mode: 'index'
            }
        },
        scales: {
            x: {
                display: true,
                grid: { color: 'rgba(255,255,255,0.03)', drawBorder: false },
                ticks: { color: '#64748b', font: { size: 10 }, maxTicksLimit: 8, maxRotation: 0 }
            },
            y: {
                display: true,
                grid: { color: 'rgba(255,255,255,0.03)', drawBorder: false },
                ticks: { color: '#64748b', font: { size: 10 } }
            }
        }
    };

    function createChart(canvasId, config) {
        const ctx = document.getElementById(canvasId);
        if (!ctx) return null;
        return new Chart(ctx.getContext('2d'), config);
    }

    function initCharts() {
        const timeLabels = [];

        // CPU Chart
        charts.cpu = createChart('chart-cpu', {
            type: 'line',
            data: {
                labels: timeLabels,
                datasets: [
                    { label: 'CPU Sistema', data: [], borderColor: '#8b5cf6', backgroundColor: 'rgba(139,92,246,0.1)', fill: true, tension: 0.3, pointRadius: 0, borderWidth: 2 },
                    { label: 'CPU Llama', data: [], borderColor: '#d946ef', backgroundColor: 'rgba(217,70,239,0.05)', fill: true, tension: 0.3, pointRadius: 0, borderWidth: 1.5 }
                ]
            },
            options: { ...chartDefaults, scales: { ...chartDefaults.scales, y: { ...chartDefaults.scales.y, min: 0, max: 100, ticks: { ...chartDefaults.scales.y.ticks, callback: v => v + '%' } } } }
        });

        // RAM Chart
        charts.ram = createChart('chart-ram', {
            type: 'line',
            data: {
                labels: timeLabels,
                datasets: [
                    { label: 'RAM Sistema', data: [], borderColor: '#d946ef', backgroundColor: 'rgba(217,70,239,0.1)', fill: true, tension: 0.3, pointRadius: 0, borderWidth: 2 },
                    { label: 'RAM Llama', data: [], borderColor: '#8b5cf6', backgroundColor: 'rgba(139,92,246,0.05)', fill: true, tension: 0.3, pointRadius: 0, borderWidth: 1.5 }
                ]
            },
            options: { ...chartDefaults, scales: { ...chartDefaults.scales, y: { ...chartDefaults.scales.y, min: 0, max: 100, ticks: { ...chartDefaults.scales.y.ticks, callback: v => v + '%' } } } }
        });

        // Temperature Chart
        charts.temp = createChart('chart-temp', {
            type: 'line',
            data: {
                labels: timeLabels,
                datasets: [
                    { label: 'Temperatura', data: [], borderColor: '#f59e0b', backgroundColor: 'rgba(245,158,11,0.1)', fill: true, tension: 0.3, pointRadius: 0, borderWidth: 2 }
                ]
            },
            options: { ...chartDefaults, scales: { ...chartDefaults.scales, y: { ...chartDefaults.scales.y, min: 20, ticks: { ...chartDefaults.scales.y.ticks, callback: v => v + '°C' } } } }
        });

        // Network Chart
        charts.net = createChart('chart-net', {
            type: 'line',
            data: {
                labels: timeLabels,
                datasets: [
                    { label: 'RX (KB/s)', data: [], borderColor: '#10b981', backgroundColor: 'rgba(16,185,129,0.1)', fill: true, tension: 0.3, pointRadius: 0, borderWidth: 2 },
                    { label: 'TX (KB/s)', data: [], borderColor: '#3b82f6', backgroundColor: 'rgba(59,130,246,0.1)', fill: true, tension: 0.3, pointRadius: 0, borderWidth: 2 }
                ]
            },
            options: { ...chartDefaults, scales: { ...chartDefaults.scales, y: { ...chartDefaults.scales.y, min: 0, ticks: { ...chartDefaults.scales.y.ticks, callback: v => v + ' KB/s' } } } }
        });

        // Disk I/O Chart
        charts.diskIo = createChart('chart-disk-io', {
            type: 'line',
            data: {
                labels: timeLabels,
                datasets: [
                    { label: 'Lectura', data: [], borderColor: '#06b6d4', backgroundColor: 'rgba(6,182,212,0.1)', fill: true, tension: 0.3, pointRadius: 0, borderWidth: 2 },
                    { label: 'Escritura', data: [], borderColor: '#f43f5e', backgroundColor: 'rgba(244,63,94,0.1)', fill: true, tension: 0.3, pointRadius: 0, borderWidth: 2 }
                ]
            },
            options: { ...chartDefaults, scales: { ...chartDefaults.scales, y: { ...chartDefaults.scales.y, min: 0, ticks: { ...chartDefaults.scales.y.ticks, callback: v => v + ' KB/s' } } } }
        });

        // Load Average Chart
        charts.load = createChart('chart-load', {
            type: 'line',
            data: {
                labels: timeLabels,
                datasets: [
                    { label: '1 min', data: [], borderColor: '#8b5cf6', tension: 0.3, pointRadius: 0, borderWidth: 2 },
                    { label: '5 min', data: [], borderColor: '#d946ef', tension: 0.3, pointRadius: 0, borderWidth: 1.5 },
                    { label: '15 min', data: [], borderColor: '#64748b', tension: 0.3, pointRadius: 0, borderWidth: 1, borderDash: [5, 5] }
                ]
            },
            options: { ...chartDefaults }
        });

        // Render legends
        renderChartLegends();
    }

    function renderChartLegends() {
        const legends = {
            'legend-cpu': [{ color: '#8b5cf6', label: 'Sistema' }, { color: '#d946ef', label: 'Llama' }],
            'legend-ram': [{ color: '#d946ef', label: 'Sistema' }, { color: '#8b5cf6', label: 'Llama' }],
            'legend-net': [{ color: '#10b981', label: 'RX' }, { color: '#3b82f6', label: 'TX' }],
            'legend-disk': [{ color: '#06b6d4', label: 'Lectura' }, { color: '#f43f5e', label: 'Escritura' }],
            'legend-load': [{ color: '#8b5cf6', label: '1m' }, { color: '#d946ef', label: '5m' }, { color: '#64748b', label: '15m' }]
        };
        for (const [id, items] of Object.entries(legends)) {
            const el = document.getElementById(id);
            if (el) {
                el.innerHTML = items.map(i =>
                    `<span class="legend-item"><span class="legend-dot" style="background:${i.color}"></span>${i.label}</span>`
                ).join('');
            }
        }
    }

    function formatTime(ts) {
        const d = new Date(ts * 1000);
        return d.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    }

    function formatUptime(seconds) {
        if (!seconds || seconds <= 0) return '0s';
        const h = Math.floor(seconds / 3600);
        const m = Math.floor((seconds % 3600) / 60);
        const s = Math.floor(seconds % 60);
        if (h > 0) return `${h}h ${m}m`;
        if (m > 0) return `${m}m ${s}s`;
        return `${s}s`;
    }

    async function fetchMetricsHistory() {
        try {
            const res = await fetch("/api/metrics/history");
            if (!res.ok) return;
            const data = await res.json();
            const history = data.history || [];
            if (history.length === 0) return;

            const labels = history.map(p => formatTime(p.t));
            const MAX_POINTS = 300;

            // Update summary cards
            const last = history[history.length - 1];
            monCurrentCpu.textContent = last.cpu + '%';
            monCurrentRam.textContent = last.ram_pct + '%';
            monCurrentTemp.textContent = last.temp !== null ? last.temp + '°C' : 'N/A';
            monCurrentUptime.textContent = formatUptime(last.llama_uptime);

            // Color code temperature
            if (last.temp !== null) {
                if (last.temp >= 80) monCurrentTemp.style.color = '#f43f5e';
                else if (last.temp >= 65) monCurrentTemp.style.color = '#f59e0b';
                else monCurrentTemp.style.color = '#10b981';
            }

            // Update sidebar extra details
            document.getElementById('hw-temp').textContent = last.temp !== null ? last.temp + '°C' : 'N/A';
            document.getElementById('hw-disk').textContent = `${last.disk_used} / ${last.disk_total} GB (${last.disk_pct}%)`;
            document.getElementById('hw-net-tx').textContent = last.net_tx_kbs + ' KB/s';
            document.getElementById('hw-net-rx').textContent = last.net_rx_kbs + ' KB/s';
            document.getElementById('hw-load').textContent = `${last.load1} / ${last.load5} / ${last.load15}`;

            // Update CPU chart
            if (charts.cpu) {
                charts.cpu.data.labels = labels;
                charts.cpu.data.datasets[0].data = history.map(p => p.cpu);
                charts.cpu.data.datasets[1].data = history.map(p => p.proc_cpu_llama);
                charts.cpu.update('none');
            }

            // Update RAM chart
            if (charts.ram) {
                charts.ram.data.labels = labels;
                charts.ram.data.datasets[0].data = history.map(p => p.ram_pct);
                // Llama RAM as % of total
                charts.ram.data.datasets[1].data = history.map(p =>
                    p.ram_total > 0 ? Math.round(p.proc_ram_llama / (p.ram_total * 1024) * 100 * 10) / 10 : 0
                );
                charts.ram.update('none');
            }

            // Update Temperature chart
            if (charts.temp) {
                charts.temp.data.labels = labels;
                charts.temp.data.datasets[0].data = history.map(p => p.temp);
                // Add threshold annotation if temp >= 80
                charts.temp.update('none');
            }

            // Update Network chart
            if (charts.net) {
                charts.net.data.labels = labels;
                charts.net.data.datasets[0].data = history.map(p => p.net_rx_kbs);
                charts.net.data.datasets[1].data = history.map(p => p.net_tx_kbs);
                charts.net.update('none');
            }

            // Update Disk I/O chart
            if (charts.diskIo) {
                charts.diskIo.data.labels = labels;
                charts.diskIo.data.datasets[0].data = history.map(p => p.disk_read_kbs);
                charts.diskIo.data.datasets[1].data = history.map(p => p.disk_write_kbs);
                charts.diskIo.update('none');
            }

            // Update Load chart
            if (charts.load) {
                charts.load.data.labels = labels;
                charts.load.data.datasets[0].data = history.map(p => p.load1);
                charts.load.data.datasets[1].data = history.map(p => p.load5);
                charts.load.data.datasets[2].data = history.map(p => p.load15);
                charts.load.update('none');
            }

            // Check alerts
            checkAlertsFromHistory(history);

        } catch (err) {
            console.error("Error fetching metrics:", err);
        }
    }

    async function checkAlertsFromHistory(history) {
        if (!history || history.length === 0) return;
        try {
            const res = await fetch("/api/alerts/check");
            if (!res.ok) return;
            const data = await res.json();
            if (data.alerts && data.alerts.length > 0 && Date.now() - lastAlertDismiss > 10000) {
                const msgs = data.alerts.map(a => {
                    const labels = { cpu: 'CPU', ram: 'RAM', temp: 'Temperatura' };
                    return `${labels[a.type] || a.type}: ${a.value}${a.type === 'temp' ? '°C' : '%'} (umbral: ${a.threshold}${a.type === 'temp' ? '°C' : '%'})`;
                });
                alertBannerText.textContent = 'ALERTA: ' + msgs.join(' | ');
                alertBanner.className = 'alert-banner alert-warning';
            } else if (!data.alerts || data.alerts.length === 0) {
                alertBanner.className = 'alert-banner hidden';
            }
        } catch (err) {
            // Ignore alert check errors
        }
    }

    async function fetchAlertConfig() {
        try {
            const res = await fetch("/api/alerts/config");
            if (!res.ok) return;
            const data = await res.json();
            toggleAlerts.checked = data.enabled;
            thresholdCpu.value = data.cpu_threshold;
            thresholdRam.value = data.ram_threshold;
            thresholdTemp.value = data.temp_threshold;
        } catch (err) {
            console.error("Error fetching alert config:", err);
        }
    }

    async function saveAlertConfig() {
        btnSaveAlerts.disabled = true;
        try {
            const res = await fetch("/api/alerts/config", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    enabled: toggleAlerts.checked,
                    cpu_threshold: parseInt(thresholdCpu.value),
                    ram_threshold: parseInt(thresholdRam.value),
                    temp_threshold: parseInt(thresholdTemp.value)
                })
            });
            const data = await res.json();
            if (data.success) {
                btnSaveAlerts.innerHTML = '<i class="fa-solid fa-circle-check"></i> Guardado';
                setTimeout(() => {
                    btnSaveAlerts.innerHTML = '<i class="fa-solid fa-floppy-disk"></i> Guardar Umbrales';
                }, 2000);
            }
        } catch (err) {
            console.error("Error saving alert config:", err);
        } finally {
            btnSaveAlerts.disabled = false;
        }
    }

    // --- MODEL BROWSER ---
    let catalogPollInterval = null;

    async function fetchCatalog() {
        try {
            const res = await fetch("/api/models/catalog");
            if (!res.ok) return;
            const data = await res.json();
            modalRamInfo.textContent = data.ram_gb + " GB";
            currentCatalog = data.catalog || [];
            renderCatalogFiltered();
        } catch (err) {
            console.error("Error fetching catalog:", err);
            modelsCatalogList.innerHTML = '<p style="color:var(--color-danger)">Error al cargar el catálogo.</p>';
        }
    }

    function renderCatalogFiltered() {
        const filtered = currentFilter === "all"
            ? currentCatalog
            : currentCatalog.filter(m => m.tags && m.tags.includes(currentFilter));
        renderCatalog(filtered);
    }

    function renderCatalog(catalog) {
        modelsCatalogList.innerHTML = "";
        catalog.forEach(model => {
            const card = document.createElement("div");
            card.className = "model-card" + (model.recommended ? " recommended" : "") + (model.downloaded ? " downloaded" : "");

            const iconClass = model.downloaded ? "fa-solid fa-circle-check" : (model.recommended ? "fa-solid fa-star" : "fa-solid fa-cube");

            card.innerHTML = `
                <div class="model-card-icon"><i class="${iconClass}"></i></div>
                <div class="model-card-info">
                    <div class="model-card-name">${model.name}</div>
                    <div class="model-card-family">${model.family}</div>
                    <div class="model-card-desc">${model.description}</div>
                    <div class="model-card-meta">
                        <span class="model-meta-tag"><i class="fa-solid fa-hard-drive"></i> ${model.size_gb} GB</span>
                        <span class="model-meta-tag"><i class="fa-solid fa-memory"></i> ${model.ram_min_gb}+ GB RAM</span>
                        <span class="model-meta-tag"><i class="fa-solid fa-bolt"></i> ${model.speed}</span>
                        <span class="model-meta-tag"><i class="fa-solid fa-star"></i> ${model.quality}</span>
                        <span class="model-meta-tag"><i class="fa-solid fa-text-height"></i> ${(model.ctx/1024).toFixed(0)}K ctx</span>
                    </div>
                </div>
                <div class="model-card-actions">
                    ${model.downloaded ? '<span class="model-badge-downloaded"><i class="fa-solid fa-check"></i> Descargado</span>' : ''}
                    ${model.recommended && !model.downloaded ? '<span class="model-badge-rec"><i class="fa-solid fa-thumbs-up"></i> Recomendado</span>' : ''}
                    ${!model.downloaded ?
                        `<button class="btn btn-primary btn-sm download-btn" data-url="${model.url}" data-name="${model.filename}" ${!model.recommended ? 'title="Tu sistema no cumple con la RAM mínima"' : ''}>
                            <i class="fa-solid fa-cloud-arrow-down"></i> Descargar
                        </button>` :
                        `<button class="btn btn-danger btn-sm delete-model-btn" data-name="${model.filename}">
                            <i class="fa-solid fa-trash"></i> Eliminar
                        </button>`
                    }
                </div>
            `;
            modelsCatalogList.appendChild(card);
        });

        // Bind download buttons
        modelsCatalogList.querySelectorAll(".download-btn").forEach(btn => {
            btn.addEventListener("click", () => startDownload(btn.dataset.url, btn.dataset.name, btn));
        });

        // Bind delete buttons
        modelsCatalogList.querySelectorAll(".delete-model-btn").forEach(btn => {
            btn.addEventListener("click", () => {
                modelToDelete = btn.dataset.name;
                deleteModelName.textContent = modelToDelete;
                modalConfirmDelete.classList.remove("hidden");
            });
        });
    }

    async function startDownload(url, filename, btn) {
        btn.disabled = true;
        btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Iniciando...';
        try {
            const res = await fetch("/api/models/download", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ url, name: filename })
            });
            const data = await res.json();
            if (data.success) {
                // Show active indicator
                downloadActiveIndicator.classList.remove("hidden");
                downloadActiveText.textContent = `Descargando ${filename}...`;
                // Start polling progress
                startDownloadPoll(filename);
            } else {
                btn.disabled = false;
                btn.innerHTML = `<i class="fa-solid fa-cloud-arrow-down"></i> Descargar`;
                alert(data.error);
            }
        } catch (err) {
            btn.disabled = false;
            btn.innerHTML = `<i class="fa-solid fa-cloud-arrow-down"></i> Descargar`;
            console.error("Download error:", err);
        }
    }

    function startDownloadPoll(filename) {
        if (catalogPollInterval) clearInterval(catalogPollInterval);
        catalogPollInterval = setInterval(async () => {
            try {
                const res = await fetch("/api/models/download/progress");
                const data = await res.json();
                const dl = data.downloads[filename];
                if (!dl) return;

                if (dl.status === "done") {
                    clearInterval(catalogPollInterval);
                    catalogPollInterval = null;
                    downloadActiveIndicator.classList.add("hidden");
                    fetchCatalog();
                    fetchModels();
                } else if (dl.status === "error") {
                    clearInterval(catalogPollInterval);
                    catalogPollInterval = null;
                    downloadActiveIndicator.classList.add("hidden");
                    alert(`Error al descargar: ${dl.error}`);
                    fetchCatalog();
                } else {
                    downloadActiveText.textContent = `${filename} - ${dl.progress}% (${dl.speed})`;
                    // Update progress bar in card if visible
                    const progressFill = modelsCatalogList.querySelector(`.progress-fill-${CSS.escape(filename)}`);
                    if (progressFill) progressFill.style.width = dl.progress + "%";
                }
            } catch (err) {
                console.error("Poll error:", err);
            }
        }, 1000);
    }

    // Open/Close Model Browser
    btnOpenModels.addEventListener("click", () => {
        modalModels.classList.remove("hidden");
        fetchCatalog();
    });

    btnCloseModels.addEventListener("click", () => {
        modalModels.classList.add("hidden");
    });

    modalModels.querySelector(".modal-overlay").addEventListener("click", () => {
        modalModels.classList.add("hidden");
    });

    // Filter buttons
    filterBtns.forEach(btn => {
        btn.addEventListener("click", () => {
            filterBtns.forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            currentFilter = btn.dataset.filter;
            renderCatalogFiltered();
        });
    });

    // Delete Confirmation
    btnCloseConfirmDelete.addEventListener("click", () => {
        modalConfirmDelete.classList.add("hidden");
        modelToDelete = null;
    });

    btnCancelDelete.addEventListener("click", () => {
        modalConfirmDelete.classList.add("hidden");
        modelToDelete = null;
    });

    modalConfirmDelete.querySelector(".modal-overlay").addEventListener("click", () => {
        modalConfirmDelete.classList.add("hidden");
        modelToDelete = null;
    });

    btnConfirmDelete.addEventListener("click", async () => {
        if (!modelToDelete) return;
        btnConfirmDelete.disabled = true;
        try {
            const res = await fetch("/api/models/delete", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name: modelToDelete })
            });
            const data = await res.json();
            if (data.success) {
                modalConfirmDelete.classList.add("hidden");
                fetchCatalog();
                fetchModels();
            } else {
                alert(data.error);
            }
        } catch (err) {
            alert("Error al eliminar modelo");
        } finally {
            btnConfirmDelete.disabled = false;
            modelToDelete = null;
        }
    });

    // --- INITIALIZATION ---
    function init() {
        // Load initial state
        updateStatus();
        fetchModels();
        initCharts();
        fetchAlertConfig();
        
        // Start polling status
        statusInterval = setInterval(updateStatus, 3000);
        
        // Start monitoring polling
        monitoringInterval = setInterval(fetchMetricsHistory, 5000);
        fetchMetricsHistory(); // Initial fetch
        
        // Register parameters events
        selectPersona.addEventListener("change", () => {
            const val = selectPersona.value;
            if (personas[val]) {
                textareaSystemPrompt.value = personas[val];
            }
        });
        
        rangeTemperature.addEventListener("input", () => {
            valTemperature.textContent = rangeTemperature.value;
        });
        
        rangeMaxTokens.addEventListener("input", () => {
            valMaxTokens.textContent = rangeMaxTokens.value;
        });
        
        // Monitoring events
        btnDismissAlert.addEventListener("click", () => {
            alertBanner.className = 'alert-banner hidden';
            lastAlertDismiss = Date.now();
        });
        
        btnSaveAlerts.addEventListener("click", saveAlertConfig);
        
        // Setup marked options
        marked.setOptions({
            highlight: function(code, lang) {
                const language = hljs.getLanguage(lang) ? lang : 'plaintext';
                return hljs.highlight(code, { language }).value;
            },
            langPrefix: 'hljs language-'
        });
    }

    // --- TAB SWITCHING ---
    tabBtns.forEach(btn => {
        btn.addEventListener("click", () => {
            const targetTab = btn.getAttribute("data-tab");
            
            // Toggle active classes
            tabBtns.forEach(b => b.classList.remove("active"));
            tabPanes.forEach(p => p.classList.remove("active"));
            
            btn.classList.add("active");
            document.getElementById(targetTab).classList.add("active");
            
            state.activeTab = targetTab;
            
            // Adjust polling timers
            if (targetTab === "tab-logs") {
                fetchLogs();
                // Poll logs every 2 seconds
                if (!logsInterval) {
                    logsInterval = setInterval(fetchLogs, 2000);
                }
            } else {
                if (logsInterval) {
                    clearInterval(logsInterval);
                    logsInterval = null;
                }
            }
        });
    });

    // --- API FUNCTIONS ---

    // Fetch and Update Status
    async function updateStatus() {
        try {
            const res = await fetch("/api/status");
            if (!res.ok) throw new Error("HTTP error");
            const data = await res.json();
            
            state.localIp = data.local_ip;
            state.subnet = data.subnet;
            state.llamaPort = data.llama_port;
            state.isServerRunning = data.llama_server_running;
            state.isWorkerRunning = data.rpc_server_running;
            state.activeModel = data.active_model;
            state.nodes = data.active_workers || [];
            
            // Update UI elements
            infoLocalIp.textContent = state.localIp;
            infoApiPort.textContent = state.llamaPort;
            infoSubnet.textContent = `Rango detectado: ${state.subnet}.1 a .254`;
            
            // Maestro status
            if (data.llama_server_running) {
                if (data.health_ok) {
                    maestroDot.className = "status-dot online";
                    maestroText.className = "status-text text-online";
                    maestroText.textContent = "Activo";
                    
                    // Enable chat inputs
                    chatInputTextarea.disabled = false;
                    btnSendMessage.disabled = false;
                    chatInputTextarea.placeholder = "Escribe tu mensaje aquí... (Ctrl+Enter para enviar)";
                    chatModelIndicator.className = "model-indicator-tag active";
                    chatModelIndicator.textContent = state.activeModel || "Conectado";
                    
                    paramsApiStatusInfo.className = "status-box-params connected";
                    paramsApiStatusInfo.innerHTML = `<i class="fa-solid fa-circle-check"></i> <span>Maestro listo para inferencia.</span>`;
                } else {
                    maestroDot.className = "status-dot loading";
                    maestroText.className = "status-text text-loading";
                    maestroText.textContent = "Cargando...";
                    
                    chatInputTextarea.disabled = true;
                    btnSendMessage.disabled = true;
                    chatInputTextarea.placeholder = "El servidor está cargando el modelo...";
                    
                    paramsApiStatusInfo.className = "status-box-params";
                    paramsApiStatusInfo.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> <span>Cargando modelo GGUF en memoria...</span>`;
                }
            } else {
                maestroDot.className = "status-dot offline";
                maestroText.className = "status-text text-offline";
                maestroText.textContent = "Desconectado";
                
                chatInputTextarea.disabled = true;
                btnSendMessage.disabled = true;
                chatInputTextarea.placeholder = "Inicia el servidor maestro para chatear...";
                chatModelIndicator.className = "model-indicator-tag";
                chatModelIndicator.textContent = "Desconectado";
                
                paramsApiStatusInfo.className = "status-box-params";
                paramsApiStatusInfo.innerHTML = `<i class="fa-solid fa-triangle-exclamation"></i> <span>Inicia el servidor maestro para habilitar la inferencia.</span>`;
            }
            
            // Worker status
            if (data.rpc_server_running) {
                workerDot.className = "status-dot online";
                workerText.className = "status-text text-online";
                workerText.textContent = `Activo (PID ${data.rpc_pid})`;
                btnStartWorker.innerHTML = `<i class="fa-solid fa-power-off"></i> Detener Worker Local`;
                btnStartWorker.className = "btn btn-danger";
            } else {
                workerDot.className = "status-dot offline";
                workerText.className = "status-text text-offline";
                workerText.textContent = "Apagado";
                btnStartWorker.innerHTML = `<i class="fa-solid fa-network-wired"></i> Iniciar Worker Local`;
                btnStartWorker.className = "btn btn-secondary";
            }
            
            // Model active badge
            if (state.activeModel) {
                infoActiveModel.textContent = state.activeModel;
            } else {
                infoActiveModel.textContent = "Ninguno cargado";
            }
            
            // Render nodes list
            renderNodesList();
            
            // Update sidebar hardware card
            if (data.hardware) {
                const hw = data.hardware;
                const sys = hw.system;
                const procs = hw.processes;
                
                // CPU bar
                document.getElementById("hw-cpu-pct").textContent = sys.cpu + "%";
                document.getElementById("hw-cpu-bar").style.width = sys.cpu + "%";
                
                // RAM bar
                document.getElementById("hw-mem-text").textContent = `${sys.mem_used_gb} / ${sys.mem_total_gb} GB (${sys.mem_pct}%)`;
                document.getElementById("hw-mem-bar").style.width = sys.mem_pct + "%";
                
                // Process details
                if (procs.llama_server.running) {
                    document.getElementById("hw-llama-cpu").textContent = procs.llama_server.cpu + "%";
                    document.getElementById("hw-llama-mem").textContent = procs.llama_server.mem_mb + " MB";
                } else {
                    document.getElementById("hw-llama-cpu").textContent = "0%";
                    document.getElementById("hw-llama-mem").textContent = "0 MB";
                }
                
                if (procs.rpc_server.running) {
                    document.getElementById("hw-rpc-cpu").textContent = procs.rpc_server.cpu + "%";
                    document.getElementById("hw-rpc-mem").textContent = procs.rpc_server.mem_mb + " MB";
                } else {
                    document.getElementById("hw-rpc-cpu").textContent = "0%";
                    document.getElementById("hw-rpc-mem").textContent = "0 MB";
                }
            }
            
            // Populate settings fields if not focused
            if (document.activeElement !== inputThreads) inputThreads.value = data.config.THREADS;
            if (document.activeElement !== inputCtxSize) inputCtxSize.value = data.config.CTX_SIZE;
            if (document.activeElement !== inputBatchSize) inputBatchSize.value = data.config.BATCH_SIZE;
            if (document.activeElement !== inputLlamaPort) inputLlamaPort.value = data.config.LLAMA_PORT;
            if (document.activeElement !== inputRpcPort) inputRpcPort.value = data.config.RPC_PORT;
            if (document.activeElement !== inputSubnet) inputSubnet.value = data.config.CLUSTER_SUBNET;
            
        } catch (err) {
            console.error("Error updates status:", err);
            maestroDot.className = "status-dot offline";
            maestroText.className = "status-text text-offline";
            maestroText.textContent = "Error Red";
        }
    }

    // Fetch list of GGUF models
    async function fetchModels() {
        try {
            const res = await fetch("/api/models");
            if (!res.ok) throw new Error();
            const data = await res.json();
            state.models = data.models;
            
            // Populate models select dropdown
            selectServerModel.innerHTML = "";
            if (state.models.length === 0) {
                selectServerModel.innerHTML = `<option value="">No hay modelos en models/</option>`;
                return;
            }
            
            state.models.forEach(model => {
                const opt = document.createElement("option");
                opt.value = model.name;
                opt.textContent = `${model.name} (${model.size_human})`;
                selectServerModel.appendChild(opt);
            });
        } catch (err) {
            console.error("Error fetching models:", err);
        }
    }

    // Scan Nodes
    async function scanNodes() {
        btnRefreshNodes.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i>`;
        btnRefreshNodes.disabled = true;
        try {
            const res = await fetch("/api/nodes");
            if (res.ok) {
                const data = await res.json();
                state.nodes = data.nodes;
                renderNodesList();
            }
        } catch (err) {
            console.error(err);
        } finally {
            btnRefreshNodes.innerHTML = `<i class="fa-solid fa-arrows-rotate"></i>`;
            btnRefreshNodes.disabled = false;
        }
    }

    // Render Nodes List
    function renderNodesList() {
        nodesListUl.innerHTML = "";
        if (state.nodes.length === 0) {
            nodesListUl.innerHTML = `<li class="empty-list">No se han detectado nodos.</li>`;
            return;
        }
        
        state.nodes.forEach(ip => {
            const li = document.createElement("li");
            
            const ipSpan = document.createElement("span");
            ipSpan.className = "node-ip";
            // Highlight local node
            const isLocal = ip === state.localIp;
            ipSpan.innerHTML = `<i class="fa-solid fa-desktop"></i> ${ip} ${isLocal ? '<span class="node-tag-local">(Este PC)</span>' : ''}`;
            
            const statusSpan = document.createElement("span");
            statusSpan.className = "node-status";
            statusSpan.innerHTML = `<i class="fa-solid fa-plug"></i> Conectado`;
            
            li.appendChild(ipSpan);
            li.appendChild(statusSpan);
            nodesListUl.appendChild(li);
        });
    }

    // --- CONTROLS ACTIONS ---

    // Start Maestro Server
    btnStartServer.addEventListener("click", async () => {
        const model = selectServerModel.value;
        if (!model) {
            alert("Por favor descarga o coloca un modelo .gguf en la carpeta models/ primero.");
            return;
        }
        
        btnStartServer.disabled = true;
        btnStartServer.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Arrancando...`;
        
        try {
            const res = await fetch("/api/control", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    action: "start_server",
                    model: model,
                    threads: parseInt(inputThreads.value),
                    ctx_size: parseInt(inputCtxSize.value),
                    batch_size: parseInt(inputBatchSize.value),
                    llama_port: parseInt(inputLlamaPort.value),
                    rpc_port: parseInt(inputRpcPort.value)
                })
            });
            
            const data = await res.json();
            if (data.success) {
                // Wait briefly and update status
                setTimeout(updateStatus, 1000);
            } else {
                alert("Error: " + data.error);
            }
        } catch (err) {
            console.error(err);
            alert("Error al iniciar el servidor maestro");
        } finally {
            btnStartServer.disabled = false;
            btnStartServer.innerHTML = `<i class="fa-solid fa-play"></i> Iniciar Maestro`;
        }
    });

    // Start/Stop Worker
    btnStartWorker.addEventListener("click", async () => {
        btnStartWorker.disabled = true;
        
        const action = state.isWorkerRunning ? "stop_worker" : "start_worker";
        
        try {
            const res = await fetch("/api/control", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ action })
            });
            const data = await res.json();
            if (data.success) {
                setTimeout(updateStatus, 1000);
            } else {
                alert("Error: " + data.error);
            }
        } catch (err) {
            console.error(err);
        } finally {
            btnStartWorker.disabled = false;
        }
    });

    // Stop All Services
    btnStopAll.addEventListener("click", async () => {
        if (!confirm("¿Seguro que deseas detener el maestro y todos los procesos del cluster locales?")) return;
        
        btnStopAll.disabled = true;
        btnStopAll.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Apagando...`;
        
        try {
            const res = await fetch("/api/control", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ action: "stop_all" })
            });
            const data = await res.json();
            if (data.success) {
                setTimeout(updateStatus, 1000);
            }
        } catch (err) {
            console.error(err);
        } finally {
            btnStopAll.disabled = false;
            btnStopAll.innerHTML = `<i class="fa-solid fa-stop"></i> Detener Todo`;
        }
    });

    btnRefreshNodes.addEventListener("click", scanNodes);

    // Save Settings
    btnSaveSettings.addEventListener("click", async () => {
        btnSaveSettings.disabled = true;
        settingsStatusMsg.textContent = "Guardando...";
        settingsStatusMsg.className = "status-msg";
        
        try {
            const res = await fetch("/api/settings", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    threads: parseInt(inputThreads.value),
                    ctx_size: parseInt(inputCtxSize.value),
                    batch_size: parseInt(inputBatchSize.value),
                    llama_port: parseInt(inputLlamaPort.value),
                    rpc_port: parseInt(inputRpcPort.value),
                    cluster_subnet: inputSubnet.value
                })
            });
            
            const data = await res.json();
            if (data.success) {
                settingsStatusMsg.textContent = "✓ Configuración guardada en cluster.conf. Reinicia el maestro para aplicar.";
                settingsStatusMsg.className = "status-msg success";
                updateStatus();
            } else {
                settingsStatusMsg.textContent = "✗ Error al guardar: " + data.error;
                settingsStatusMsg.className = "status-msg error";
            }
        } catch (err) {
            settingsStatusMsg.textContent = "✗ Error de red";
            settingsStatusMsg.className = "status-msg error";
        } finally {
            btnSaveSettings.disabled = false;
        }
    });

    // --- PLAYGROUND CHAT PLAYGROUND ---

    btnClearChat.addEventListener("click", () => {
        chatMessagesContainer.innerHTML = `
            <div class="message system-msg">
                <div class="avatar"><i class="fa-solid fa-robot"></i></div>
                <div class="content">
                    <p>Conversación limpia. Puedes comenzar de nuevo.</p>
                </div>
            </div>`;
        state.chatMessages = [];
    });

    // Helper to append message to Chat UI
    function appendMessage(role, text) {
        const msgDiv = document.createElement("div");
        msgDiv.className = `message ${role}-msg`;
        
        const avatar = document.createElement("div");
        avatar.className = "avatar";
        avatar.innerHTML = role === "user" ? '<i class="fa-solid fa-user"></i>' : '<i class="fa-solid fa-robot"></i>';
        
        const contentDiv = document.createElement("div");
        contentDiv.className = "content";
        
        if (role === "user") {
            contentDiv.textContent = text;
        } else {
            contentDiv.innerHTML = marked.parse(text);
            // Highlight code blocks
            contentDiv.querySelectorAll("pre code").forEach(block => {
                hljs.highlightElement(block);
            });
        }
        
        msgDiv.appendChild(avatar);
        msgDiv.appendChild(contentDiv);
        chatMessagesContainer.appendChild(msgDiv);
        
        // Auto scroll
        chatMessagesContainer.scrollTop = chatMessagesContainer.scrollHeight;
        
        return contentDiv;
    }

    // Send chat message (SSE stream directly to llama-server)
    async function handleChatSend() {
        const prompt = chatInputTextarea.value.trim();
        if (!prompt) return;
        
        // Clear textarea
        chatInputTextarea.value = "";
        
        // Append user prompt to UI and local history
        appendMessage("user", prompt);
        state.chatMessages.push({ role: "user", content: prompt });
        
        // Prepare API call
        chatInputTextarea.disabled = true;
        btnSendMessage.disabled = true;
        
        // Append placeholder assistant response
        const assistantContentNode = appendMessage("assistant", "...");
        
        // Connect to llama-server OpenAI endpoint
        const targetUrl = `http://${state.localIp}:${state.llamaPort}/v1/chat/completions`;
        
        // We prepend the system prompt if present
        const messages = [];
        const systemPrompt = textareaSystemPrompt.value.trim();
        if (systemPrompt) {
            messages.push({ role: "system", content: systemPrompt });
        }
        
        // Add chat history (up to last 10 messages for memory context efficiency)
        const historySlice = state.chatMessages.slice(-10);
        messages.push(...historySlice);
        
        try {
            const response = await fetch(targetUrl, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    messages: messages,
                    temperature: parseFloat(rangeTemperature.value),
                    max_tokens: parseInt(rangeMaxTokens.value),
                    stream: true
                })
            });
            
            if (!response.ok) throw new Error("Server responded with error status");
            
            const reader = response.body.getReader();
            const decoder = new TextDecoder("utf-8");
            
            let assistantResponseText = "";
            assistantContentNode.textContent = ""; // Clear loader
            
            let done = false;
            while (!done) {
                const { value, done: readerDone } = await reader.read();
                done = readerDone;
                if (value) {
                    const chunk = decoder.decode(value, { stream: !done });
                    // Parse Event-Stream
                    const lines = chunk.split("\n");
                    for (let line of lines) {
                        line = line.trim();
                        if (line.startsWith("data: ")) {
                            const dataStr = line.substring(6);
                            if (dataStr === "[DONE]") break;
                            try {
                                const parsed = JSON.parse(dataStr);
                                const content = parsed.choices[0].delta.content || "";
                                if (content) {
                                    assistantResponseText += content;
                                    
                                    // Parse Markdown in real time (may flicker, but marked is fast)
                                    assistantContentNode.innerHTML = marked.parse(assistantResponseText);
                                    
                                    // Highlight code blocks
                                    assistantContentNode.querySelectorAll("pre code").forEach(block => {
                                        hljs.highlightElement(block);
                                    });
                                    
                                    chatMessagesContainer.scrollTop = chatMessagesContainer.scrollHeight;
                                }
                            } catch (e) {
                                // JSON partial chunks, ignore
                            }
                        }
                    }
                }
            }
            
            // Save final answer to state
            state.chatMessages.push({ role: "assistant", content: assistantResponseText });
            
        } catch (err) {
            console.error(err);
            assistantContentNode.innerHTML = `<span style="color: var(--color-danger);"><i class="fa-solid fa-circle-exclamation"></i> Error al conectar con Llama-Server: ${err.message}. Verifica que el puerto esté libre y que no haya firewalls bloqueando la comunicación.</span>`;
        } finally {
            chatInputTextarea.disabled = false;
            btnSendMessage.disabled = false;
            chatInputTextarea.focus();
        }
    }

    btnSendMessage.addEventListener("click", handleChatSend);
    chatInputTextarea.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            handleChatSend();
        }
    });

    // --- BENCHMARK PANEL ---

    btnRunBenchmark.addEventListener("click", async () => {
        if (!state.isServerRunning) {
            alert("Debes iniciar el servidor maestro antes de correr un benchmark.");
            return;
        }
        
        btnRunBenchmark.disabled = true;
        btnRunBenchmark.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Ejecutando...`;
        
        // Reset gauges
        benchValTps.textContent = "...";
        benchValFirstToken.textContent = "...";
        benchValTotalTime.textContent = "...";
        benchValCount.textContent = "...";
        
        benchmarkOutputPreviewText.textContent = "Enviando prompt de prueba al Maestro y computando velocidad en el cluster...";
        benchmarkOutputPreviewText.className = "output-preview-box";
        
        try {
            const res = await fetch("/api/benchmark", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    prompt: benchmarkPrompt.value,
                    max_tokens: parseInt(benchmarkTokens.value)
                })
            });
            
            const data = await res.json();
            if (data.success) {
                // Update stats
                benchValTps.textContent = data.tokens_per_sec;
                benchValFirstToken.textContent = data.prompt_eval_ms;
                benchValTotalTime.textContent = (data.total_ms / 1000).toFixed(2);
                benchValCount.textContent = data.tokens_count;
                
                // Show preview
                benchmarkOutputPreviewText.textContent = data.response_preview;
                benchmarkOutputPreviewText.className = "output-preview-box completed";
            } else {
                benchmarkOutputPreviewText.textContent = "Error: " + data.error;
            }
        } catch (err) {
            console.error(err);
            benchmarkOutputPreviewText.textContent = "Error de conexión con el backend.";
        } finally {
            btnRunBenchmark.disabled = false;
            btnRunBenchmark.innerHTML = `<i class="fa-solid fa-play-circle"></i> Ejecutar Test`;
        }
    });

    // --- LOGS & DIAGNOSTICS ---

    async function fetchLogs() {
        const type = selectLogType.value;
        try {
            const res = await fetch(`/api/logs?type=${type}&lines=120`);
            if (res.ok) {
                const data = await res.json();
                terminalPre.textContent = data.content || `[Consola vacía. No hay eventos registrados en ${type}.log]`;
                // Keep scroll at bottom of terminal
                terminalPre.parentElement.scrollTop = terminalPre.parentElement.scrollHeight;
            }
        } catch (err) {
            console.error("Error reading logs:", err);
        }
    }

    selectLogType.addEventListener("change", fetchLogs);
    btnRefreshLogs.addEventListener("click", fetchLogs);
    
    btnCopyLogs.addEventListener("click", () => {
        navigator.clipboard.writeText(terminalPre.textContent)
            .then(() => {
                const origText = btnCopyLogs.innerHTML;
                btnCopyLogs.innerHTML = `<i class="fa-solid fa-circle-check"></i> Copiado!`;
                setTimeout(() => { btnCopyLogs.innerHTML = origText; }, 2000);
            })
            .catch(err => console.error(err));
    });

    // Run diag command
    btnRunDiag.addEventListener("click", async () => {
        btnRunDiag.disabled = true;
        btnRunDiag.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Ejecutando Diagnóstico...`;
        diagOutputBox.textContent = "Escaneando interfaces locales, midiendo memoria libre, CPU y buscando hosts activos en la red LAN. Espera un momento...";
        
        try {
            const res = await fetch("/api/diag");
            if (res.ok) {
                const data = await res.json();
                diagOutputBox.textContent = data.output;
            } else {
                diagOutputBox.textContent = "Falló el diagnóstico del sistema.";
            }
        } catch (err) {
            diagOutputBox.textContent = "Error al comunicarse con el script de diagnóstico: " + err;
        } finally {
            btnRunDiag.disabled = false;
            btnRunDiag.innerHTML = `<i class="fa-solid fa-heart-pulse"></i> Ejecutar Diagnóstico`;
        }
    });

    // Start
    init();
});
