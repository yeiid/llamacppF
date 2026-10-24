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
    const btnStopGeneration = document.getElementById("btn-stop-generation");
    const btnClearChat = document.getElementById("btn-clear-chat");
    const chatModelIndicator = document.getElementById("chat-model-indicator");
    const selectPersona = document.getElementById("select-persona");
    const rangeTemperature = document.getElementById("range-temperature");
    const valTemperature = document.getElementById("val-temperature");
    const rangeMaxTokens = document.getElementById("range-max-tokens");
    const valMaxTokens = document.getElementById("val-max-tokens");
    const textareaSystemPrompt = document.getElementById("textarea-system-prompt");
    const paramsApiStatusInfo = document.getElementById("params-api-status-info");
    let currentChatAbortController = null;
    
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
    const inputNgl = document.getElementById("input-ngl");
    const inputKvCache = document.getElementById("input-kv-cache");
    const inputLlamaPort = document.getElementById("input-llama-port");
    const inputRpcPort = document.getElementById("input-rpc-port");
    const inputSubnet = document.getElementById("input-subnet");
    const inputCustomNodes = document.getElementById("input-custom-nodes");
    const inputExcludedNodes = document.getElementById("input-excluded-nodes");
    const inputRpcCache = document.getElementById("input-rpc-cache");
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
    const inputCustomModelUrl = document.getElementById("input-custom-model-url");
    const btnDownloadCustomUrl = document.getElementById("btn-download-custom-url");
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
        hermes: "Eres Hermes, un agente autónomo local de razonamiento profundo y orquestación técnica. Analizas los problemas paso a paso (<thought>), estructuras planes accionables, generas código modular listo para producción y utilizas esquemas JSON o herramientas cuando el usuario lo requiere.",
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
        let filtered = currentCatalog;
        if (currentFilter === "downloaded") {
            filtered = currentCatalog.filter(m => m.downloaded);
        } else if (currentFilter !== "all") {
            filtered = currentCatalog.filter(m => m.tags && m.tags.includes(currentFilter));
        }
        renderCatalog(filtered);
    }

    function renderCatalog(catalog) {
        modelsCatalogList.innerHTML = "";
        if (catalog.length === 0) {
            modelsCatalogList.innerHTML = '<p style="color:var(--color-text-dim);padding:16px;">No hay modelos en esta categoría.</p>';
            return;
        }
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
                        </button>
                        <div class="model-download-progress hidden" id="dl-box-${model.filename}">
                            <div class="progress-bar-bg">
                                <div class="progress-bar-fill progress-fill-${model.filename}" style="width: 0%"></div>
                            </div>
                            <span class="progress-text progress-txt-${model.filename}">0%</span>
                            <button class="btn btn-danger btn-sm cancel-dl-btn" data-name="${model.filename}">
                                <i class="fa-solid fa-xmark"></i> Cancelar
                            </button>
                        </div>` :
                        `<button class="btn btn-primary btn-sm use-model-btn" data-name="${model.filename}" title="Seleccionar y cargar este modelo en el Maestro">
                            <i class="fa-solid fa-play"></i> Seleccionar y Cargar
                        </button>
                        <button class="btn btn-danger btn-sm delete-model-btn" data-name="${model.filename}">
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

        // Bind cancel download buttons
        modelsCatalogList.querySelectorAll(".cancel-dl-btn").forEach(btn => {
            btn.addEventListener("click", () => cancelDownload(btn.dataset.name));
        });

        // Bind use/select model buttons
        modelsCatalogList.querySelectorAll(".use-model-btn").forEach(btn => {
            btn.addEventListener("click", async () => {
                const fname = btn.dataset.name;
                await fetchModels();
                selectServerModel.value = fname;
                const selectChatModel = document.getElementById("select-chat-model");
                if (selectChatModel) selectChatModel.value = fname;
                modalModels.classList.add("hidden");
                btnStartServer.click();
            });
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

    async function cancelDownload(filename) {
        try {
            await fetch("/api/models/download/cancel", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name: filename })
            });
            if (catalogPollInterval) {
                clearInterval(catalogPollInterval);
                catalogPollInterval = null;
            }
            downloadActiveIndicator.classList.add("hidden");
            fetchCatalog();
        } catch (err) {
            console.error("Cancel download error:", err);
        }
    }

    async function startDownload(url, filename, btn) {
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Iniciando...';
        }
        try {
            const res = await fetch("/api/models/download", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ url, name: filename })
            });
            const data = await res.json();
            if (data.success) {
                if (btn) btn.classList.add("hidden");
                const dlBox = document.getElementById(`dl-box-${filename}`);
                if (dlBox) dlBox.classList.remove("hidden");
                // Show active indicator
                downloadActiveIndicator.classList.remove("hidden");
                downloadActiveText.textContent = `Descargando ${filename}...`;
                // Start polling progress
                startDownloadPoll(filename);
            } else {
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = `<i class="fa-solid fa-cloud-arrow-down"></i> Descargar`;
                }
                alert(data.error);
            }
        } catch (err) {
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = `<i class="fa-solid fa-cloud-arrow-down"></i> Descargar`;
            }
            console.error("Download error:", err);
        }
    }

    if (btnDownloadCustomUrl) {
        btnDownloadCustomUrl.addEventListener("click", () => {
            const url = inputCustomModelUrl.value.trim();
            if (!url || !url.toLowerCase().includes(".gguf")) {
                alert("Ingresa una URL directa válida que apunte a un archivo .gguf");
                return;
            }
            let filename = url.split("/").pop().split("?")[0];
            if (!filename.endsWith(".gguf")) filename += ".gguf";
            inputCustomModelUrl.value = "";
            startDownload(url, filename, btnDownloadCustomUrl);
        });
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
                    if (btnDownloadCustomUrl) {
                        btnDownloadCustomUrl.disabled = false;
                        btnDownloadCustomUrl.classList.remove("hidden");
                        btnDownloadCustomUrl.innerHTML = `<i class="fa-solid fa-download"></i> Descargar URL`;
                    }
                    fetchCatalog();
                    fetchModels();
                } else if (dl.status === "error" || dl.status === "cancelled") {
                    clearInterval(catalogPollInterval);
                    catalogPollInterval = null;
                    downloadActiveIndicator.classList.add("hidden");
                    if (btnDownloadCustomUrl) {
                        btnDownloadCustomUrl.disabled = false;
                        btnDownloadCustomUrl.classList.remove("hidden");
                        btnDownloadCustomUrl.innerHTML = `<i class="fa-solid fa-download"></i> Descargar URL`;
                    }
                    if (dl.status === "error") {
                        alert(`Error al descargar: ${dl.error}`);
                    }
                    fetchCatalog();
                } else {
                    downloadActiveText.textContent = `${filename} - ${dl.progress}% (${dl.speed})`;
                    // Update progress bar in card if visible
                    const progressFill = modelsCatalogList.querySelector(`.progress-fill-${CSS.escape(filename)}`);
                    if (progressFill) progressFill.style.width = dl.progress + "%";
                    const progressTxt = modelsCatalogList.querySelector(`.progress-txt-${CSS.escape(filename)}`);
                    if (progressTxt) progressTxt.textContent = `${dl.progress}% (${dl.speed})`;
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
            state.nodesDetail = data.nodes_detail || [];
            
            // Update UI elements
            infoLocalIp.textContent = state.localIp;
            infoApiPort.textContent = state.llamaPort;
            infoSubnet.textContent = `Rango detectado: ${state.subnet}.1 a .254`;
            const nativeWebUiLink = document.getElementById("link-native-webui");
            if (nativeWebUiLink) {
                const hostForLink = window.location.hostname || "127.0.0.1";
                nativeWebUiLink.href = `http://${hostForLink}:${state.llamaPort}`;
            }
            
            // Maestro status
            if (data.llama_server_running) {
                if (data.health_ok) {
                    maestroDot.className = "status-dot online";
                    maestroText.className = "status-text text-online";
                    maestroText.textContent = "Activo";
                    
                    // Enable chat inputs if not actively generating
                    if (!currentChatAbortController) {
                        chatInputTextarea.disabled = false;
                        btnSendMessage.disabled = false;
                    }
                    chatInputTextarea.placeholder = "Escribe tu mensaje aquí... (Enter para enviar)";
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
            if (inputNgl && document.activeElement !== inputNgl) inputNgl.value = data.config.NGL || "auto";
            if (inputKvCache && document.activeElement !== inputKvCache) inputKvCache.value = data.config.KV_CACHE_TYPE || "f16";
            if (inputCustomNodes && document.activeElement !== inputCustomNodes) inputCustomNodes.value = data.config.CUSTOM_NODES || "";
            if (inputExcludedNodes && document.activeElement !== inputExcludedNodes) inputExcludedNodes.value = data.config.EXCLUDED_NODES || "";
            if (inputRpcCache) inputRpcCache.checked = String(data.config.RPC_CACHE || "true").toLowerCase() === "true";
            
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
            const selectToolsModel = document.getElementById("select-tools-model");
            const selectChatModel = document.getElementById("select-chat-model");
            const prevSelected = selectServerModel.value || state.activeModel || "";
            
            // Populate models select dropdowns
            selectServerModel.innerHTML = "";
            if (selectToolsModel) selectToolsModel.innerHTML = "";
            if (selectChatModel) selectChatModel.innerHTML = "";
            if (state.models.length === 0) {
                selectServerModel.innerHTML = `<option value="">No hay modelos en models/</option>`;
                if (selectToolsModel) selectToolsModel.innerHTML = `<option value="">Sin modelos en models/</option>`;
                if (selectChatModel) selectChatModel.innerHTML = `<option value="">Sin modelos descargados</option>`;
                return;
            }
            
            state.models.forEach(model => {
                const opt = document.createElement("option");
                opt.value = model.name;
                opt.textContent = `${model.name} (${model.size_human})`;
                selectServerModel.appendChild(opt);
                if (selectToolsModel) selectToolsModel.appendChild(opt.cloneNode(true));
                if (selectChatModel) selectChatModel.appendChild(opt.cloneNode(true));
            });

            if (prevSelected && state.models.some(m => m.name === prevSelected)) {
                selectServerModel.value = prevSelected;
                if (selectToolsModel) selectToolsModel.value = prevSelected;
                if (selectChatModel) selectChatModel.value = prevSelected;
            }
        } catch (err) {
            console.error("Error fetching models:", err);
        }
    }

    const selectChatModelEl = document.getElementById("select-chat-model");
    const btnChatLoadModelEl = document.getElementById("btn-chat-load-model");
    if (selectChatModelEl) {
        selectChatModelEl.addEventListener("change", () => {
            selectServerModel.value = selectChatModelEl.value;
        });
    }
    if (selectServerModel) {
        selectServerModel.addEventListener("change", () => {
            if (selectChatModelEl) selectChatModelEl.value = selectServerModel.value;
        });
    }
    if (btnChatLoadModelEl) {
        btnChatLoadModelEl.addEventListener("click", () => {
            if (selectChatModelEl && selectChatModelEl.value) {
                selectServerModel.value = selectChatModelEl.value;
            }
            btnStartServer.click();
        });
    }

    // Scan Nodes
    async function scanNodes() {
        btnRefreshNodes.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i>`;
        btnRefreshNodes.disabled = true;
        try {
            const res = await fetch("/api/nodes");
            if (res.ok) {
                const data = await res.json();
                state.nodes = data.nodes || [];
                state.nodesDetail = data.nodes_detail || [];
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
        const details = (state.nodesDetail && state.nodesDetail.length > 0)
            ? state.nodesDetail
            : state.nodes.map(ip => ({ ip, latency_ms: null, is_local: ip === state.localIp, is_custom: false }));

        if (details.length === 0) {
            nodesListUl.innerHTML = `<li class="empty-list">No se han detectado nodos.</li>`;
            return;
        }
        
        details.forEach(node => {
            const li = document.createElement("li");
            
            const ipSpan = document.createElement("span");
            ipSpan.className = "node-ip";
            const isLocal = node.is_local || node.ip === state.localIp;
            const customTag = node.is_custom ? ' <span class="node-tag-custom">[manual]</span>' : '';
            ipSpan.innerHTML = `<i class="fa-solid fa-desktop"></i> ${node.ip}${isLocal ? ' <span class="node-tag-local">(Este PC)</span>' : ''}${customTag}`;
            
            const statusSpan = document.createElement("span");
            statusSpan.className = "node-status";
            const latStr = node.latency_ms !== null && node.latency_ms !== undefined ? ` <span class="node-latency">${node.latency_ms}ms</span>` : '';
            statusSpan.innerHTML = `<i class="fa-solid fa-plug"></i> RPC${latStr}`;
            
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
                    rpc_port: parseInt(inputRpcPort.value),
                    ngl: inputNgl ? inputNgl.value : "auto",
                    kv_cache_type: inputKvCache ? inputKvCache.value : "f16"
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
                    cluster_subnet: inputSubnet.value,
                    ngl: inputNgl ? inputNgl.value.trim() : "auto",
                    kv_cache_type: inputKvCache ? inputKvCache.value : "f16",
                    rpc_cache: inputRpcCache ? inputRpcCache.checked : true,
                    custom_nodes: inputCustomNodes ? inputCustomNodes.value.trim() : "",
                    excluded_nodes: inputExcludedNodes ? inputExcludedNodes.value.trim() : ""
                })
            });
            
            const data = await res.json();
            if (data.success) {
                settingsStatusMsg.textContent = "✓ Configuración guardada en cluster.conf y opencode.json sincronizado.";
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
        if (currentChatAbortController) {
            currentChatAbortController.abort();
            currentChatAbortController = null;
        }
        chatMessagesContainer.innerHTML = `
            <div class="message system-msg">
                <div class="avatar"><i class="fa-solid fa-robot"></i></div>
                <div class="content">
                    <p>Conversación limpia. Puedes comenzar de nuevo.</p>
                </div>
            </div>`;
        state.chatMessages = [];
    });

    if (btnStopGeneration) {
        btnStopGeneration.addEventListener("click", () => {
            if (currentChatAbortController) {
                currentChatAbortController.abort();
                currentChatAbortController = null;
            }
        });
    }

    // --- CODE STUDIO & SNIPPETS STATE ---
    let sessionSnippets = [];
    let activeCodeContent = "# Selecciona o genera código en el Chat para visualizarlo, editarlo o copiarlo con 1 clic.\n";
    const langExtMap = {
        python: "py", py: "py", javascript: "js", js: "js", typescript: "ts", ts: "ts",
        html: "html", css: "css", bash: "sh", sh: "sh", shell: "sh",
        cpp: "cpp", c: "c", json: "json", sql: "sql", markdown: "md", md: "md"
    };
    const extLangMap = {
        py: "python", js: "javascript", ts: "javascript", html: "html", css: "css",
        sh: "bash", cpp: "cpp", c: "cpp", json: "json", sql: "sql", md: "markdown"
    };

    function copyTextWithFeedback(text, btnElement, labelAfter = "Copiado!") {
        navigator.clipboard.writeText(text).then(() => {
            if (!btnElement) return;
            const orig = btnElement.innerHTML;
            btnElement.innerHTML = `<i class="fa-solid fa-check"></i> ${labelAfter}`;
            btnElement.classList.add("copied-ok");
            setTimeout(() => {
                btnElement.innerHTML = orig;
                btnElement.classList.remove("copied-ok");
            }, 1800);
        });
    }

    function switchToTab(tabId) {
        const targetBtn = document.querySelector(`.tab-btn[data-tab="${tabId}"]`);
        if (targetBtn) targetBtn.click();
    }

    function openCodeInStudio(code, lang = "python", suggestedFilename = "") {
        activeCodeContent = code;
        const cleanLang = (lang || "python").toLowerCase().replace(/^language-/, "");
        const ext = langExtMap[cleanLang] || "txt";
        const filenameInput = document.getElementById("code-filename");
        const langSelect = document.getElementById("code-lang");
        const editorTextarea = document.getElementById("code-editor-textarea");
        const highlightedView = document.getElementById("code-highlighted-view");
        const statsInfo = document.getElementById("code-stats-info");

        if (filenameInput) {
            filenameInput.value = suggestedFilename || `snippet_${Date.now().toString().slice(-4)}.${ext}`;
        }
        if (langSelect && extLangMap[ext]) {
            langSelect.value = extLangMap[ext];
        }
        if (editorTextarea) {
            editorTextarea.value = code;
        }
        if (highlightedView) {
            highlightedView.className = `hljs language-${extLangMap[ext] || "plaintext"}`;
            highlightedView.textContent = code;
            hljs.highlightElement(highlightedView);
        }
        if (statsInfo) {
            const lines = code.split("\n").length;
            const bytes = new Blob([code]).size;
            statsInfo.textContent = `${lines} líneas | ${bytes} bytes`;
        }
        // Auto refresh live preview if HTML/JS
        const previewPane = document.getElementById("code-preview-pane");
        if (previewPane && !previewPane.classList.contains("hidden")) {
            renderLivePreview();
        }
    }

    function addSessionSnippet(code, lang) {
        const cleanLang = (lang || "txt").toLowerCase().replace(/^language-/, "");
        const ext = langExtMap[cleanLang] || "txt";
        // Avoid exact duplicate of last snippet
        if (sessionSnippets.length > 0 && sessionSnippets[0].code === code) return;
        const idx = sessionSnippets.length + 1;
        const item = {
            id: `chat_${Date.now()}_${idx}`,
            name: `chat_bloque_${idx}.${ext}`,
            lang: cleanLang,
            code: code,
            lines: code.split("\n").length,
            time: new Date().toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" })
        };
        sessionSnippets.unshift(item);
        const badge = document.getElementById("code-count-badge");
        if (badge) badge.textContent = sessionSnippets.length;
        renderSessionSnippets();
        // Automatically load latest snippet in Code Studio
        openCodeInStudio(item.code, item.lang, item.name);
    }

    function renderSessionSnippets() {
        const listEl = document.getElementById("session-snippets-list");
        if (!listEl) return;
        if (sessionSnippets.length === 0) {
            listEl.innerHTML = `<div class="empty-snippets">Los bloques de código generados en el chat aparecerán aquí automáticamente.</div>`;
            return;
        }
        listEl.innerHTML = "";
        sessionSnippets.forEach(item => {
            const row = document.createElement("div");
            row.className = "snippet-item";
            row.innerHTML = `
                <div class="snippet-main">
                    <span class="snippet-name"><i class="fa-solid fa-code"></i> ${item.name}</span>
                    <span class="snippet-meta">${item.lines} lín • ${item.time}</span>
                </div>
                <div class="snippet-item-actions">
                    <button class="btn-icon snippet-copy-btn" title="Copiar rápido"><i class="fa-solid fa-copy"></i></button>
                </div>
            `;
            row.querySelector(".snippet-main").addEventListener("click", () => {
                openCodeInStudio(item.code, item.lang, item.name);
            });
            row.querySelector(".snippet-copy-btn").addEventListener("click", (e) => {
                e.stopPropagation();
                copyTextWithFeedback(item.code, e.currentTarget, "");
            });
            listEl.appendChild(row);
        });
    }

    // Decorate <pre><code> inside a chat message with 1-click Copy, Open in Studio & Save
    function decorateCodeBlocks(containerNode, finalizeExtract = false) {
        containerNode.querySelectorAll("pre code").forEach((block, i) => {
            hljs.highlightElement(block);
            const pre = block.parentElement;
            if (!pre || pre.parentElement.classList.contains("chat-code-wrapper")) return;

            const classList = Array.from(block.classList);
            const langClass = classList.find(c => c.startsWith("language-")) || "language-plaintext";
            const lang = langClass.replace("language-", "") || "code";
            const rawCode = block.textContent;
            const lineCount = rawCode.split("\n").length;

            const wrapper = document.createElement("div");
            wrapper.className = "chat-code-wrapper";

            const header = document.createElement("div");
            header.className = "chat-code-header";
            header.innerHTML = `
                <span class="chat-code-lang"><i class="fa-solid fa-terminal"></i> ${lang.toUpperCase()} <small>(${lineCount} líneas)</small></span>
                <div class="chat-code-btns">
                    <button type="button" class="btn-code-action act-copy" title="Copiar código con 1 clic">
                        <i class="fa-solid fa-copy"></i> Copiar
                    </button>
                    <button type="button" class="btn-code-action act-studio" title="Abrir en Code Studio para editar o previsualizar">
                        <i class="fa-solid fa-up-right-from-square"></i> Abrir en Studio
                    </button>
                    <button type="button" class="btn-code-action act-save" title="Guardar directamente en workspace_code/">
                        <i class="fa-solid fa-floppy-disk"></i> Guardar
                    </button>
                </div>
            `;

            header.querySelector(".act-copy").addEventListener("click", (e) => {
                copyTextWithFeedback(block.textContent, e.currentTarget, "Copiado");
            });
            header.querySelector(".act-studio").addEventListener("click", () => {
                const ext = langExtMap[lang.toLowerCase()] || "txt";
                openCodeInStudio(block.textContent, lang, `codigo_chat_${i + 1}.${ext}`);
                switchToTab("tab-code");
            });
            header.querySelector(".act-save").addEventListener("click", async (e) => {
                const btn = e.currentTarget;
                const ext = langExtMap[lang.toLowerCase()] || "txt";
                const fname = `chat_${Date.now().toString().slice(-5)}.${ext}`;
                const res = await fetch("/api/snippets/save", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ filename: fname, content: block.textContent })
                });
                const data = await res.json();
                if (data.success) {
                    btn.innerHTML = `<i class="fa-solid fa-check"></i> ${data.filename}`;
                    fetchSavedSnippets();
                }
            });

            pre.parentNode.insertBefore(wrapper, pre);
            wrapper.appendChild(header);
            wrapper.appendChild(pre);

            if (finalizeExtract && rawCode.trim().length > 0) {
                addSessionSnippet(rawCode, lang);
            }
        });
    }

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
            decorateCodeBlocks(contentDiv, false);
        }
        
        msgDiv.appendChild(avatar);
        msgDiv.appendChild(contentDiv);
        chatMessagesContainer.appendChild(msgDiv);
        
        // Auto scroll
        chatMessagesContainer.scrollTop = chatMessagesContainer.scrollHeight;
        
        return contentDiv;
    }

    // Send chat message via backend SSE proxy (/api/chat) with real-time token speed validation
    async function handleChatSend() {
        const prompt = chatInputTextarea.value.trim();
        if (!prompt) return;
        
        chatInputTextarea.value = "";
        appendMessage("user", prompt);
        state.chatMessages.push({ role: "user", content: prompt });
        
        chatInputTextarea.disabled = true;
        btnSendMessage.disabled = true;
        btnSendMessage.classList.add("hidden");
        if (btnStopGeneration) btnStopGeneration.classList.remove("hidden");
        
        const assistantContentNode = appendMessage("assistant", "...");
        const bodyContainer = document.createElement("div");
        bodyContainer.className = "msg-markdown-body";
        bodyContainer.textContent = "Procesando prompt...";
        const metricsBar = document.createElement("div");
        metricsBar.className = "msg-metrics-bar";
        metricsBar.innerHTML = `<span><i class="fa-solid fa-spinner fa-spin"></i> Midiendo velocidad de tokens...</span>`;
        assistantContentNode.innerHTML = "";
        assistantContentNode.appendChild(bodyContainer);
        assistantContentNode.appendChild(metricsBar);

        const liveBadge = document.getElementById("chat-live-speed-badge");
        const liveTpsVal = document.getElementById("chat-live-tps-val");
        if (liveBadge) liveBadge.classList.remove("hidden");

        const messages = [];
        const systemPrompt = textareaSystemPrompt.value.trim();
        if (systemPrompt) {
            messages.push({ role: "system", content: systemPrompt });
        }
        const historySlice = state.chatMessages.slice(-10);
        messages.push(...historySlice);
        
        currentChatAbortController = new AbortController();
        let assistantResponseText = "";
        const reqStartMs = performance.now();
        let firstTokenMs = null;
        let chunkTokenCount = 0;
        let serverTimings = null;
        
        try {
            const response = await fetch("/api/chat", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                signal: currentChatAbortController.signal,
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
            bodyContainer.textContent = "";
            
            let done = false;
            while (!done) {
                const { value, done: readerDone } = await reader.read();
                done = readerDone;
                if (value) {
                    const chunk = decoder.decode(value, { stream: !done });
                    const lines = chunk.split("\n");
                    for (let line of lines) {
                        line = line.trim();
                        if (line.startsWith("data: ")) {
                            const dataStr = line.substring(6);
                            if (dataStr === "[DONE]") break;
                            try {
                                const parsed = JSON.parse(dataStr);
                                if (parsed.error) {
                                    throw new Error(parsed.error);
                                }
                                if (parsed.timings) {
                                    serverTimings = parsed.timings;
                                }
                                const content = (parsed.choices && parsed.choices[0] && parsed.choices[0].delta && parsed.choices[0].delta.content) || "";
                                if (content) {
                                    const nowMs = performance.now();
                                    if (firstTokenMs === null) {
                                        firstTokenMs = nowMs - reqStartMs;
                                    }
                                    chunkTokenCount += 1;
                                    assistantResponseText += content;
                                    
                                    bodyContainer.innerHTML = marked.parse(assistantResponseText);
                                    decorateCodeBlocks(bodyContainer, false);

                                    // Compute live t/s
                                    const genElapsedSec = Math.max(0.05, (nowMs - (reqStartMs + firstTokenMs)) / 1000);
                                    const liveTps = serverTimings && serverTimings.predicted_per_second
                                        ? serverTimings.predicted_per_second.toFixed(2)
                                        : (chunkTokenCount / genElapsedSec).toFixed(2);
                                    if (liveTpsVal) liveTpsVal.textContent = liveTps;
                                    metricsBar.innerHTML = `
                                        <span class="m-pill m-tps"><i class="fa-solid fa-bolt"></i> <strong>${liveTps}</strong> tokens/s</span>
                                        <span class="m-pill"><i class="fa-solid fa-hourglass-start"></i> TTFT: <strong>${Math.round(firstTokenMs)}</strong> ms</span>
                                        <span class="m-pill"><i class="fa-solid fa-coins"></i> <strong>${chunkTokenCount}</strong> tokens</span>
                                    `;
                                    
                                    chatMessagesContainer.scrollTop = chatMessagesContainer.scrollHeight;
                                }
                            } catch (e) {
                                // Ignore partial JSON chunks
                            }
                        }
                    }
                }
            }
            
            // Finalize code blocks & extract to Code Studio
            bodyContainer.innerHTML = marked.parse(assistantResponseText);
            decorateCodeBlocks(bodyContainer, true);

            const totalElapsedSec = ((performance.now() - reqStartMs) / 1000).toFixed(2);
            const finalGenTps = serverTimings && serverTimings.predicted_per_second
                ? serverTimings.predicted_per_second.toFixed(2)
                : (chunkTokenCount / Math.max(0.1, (performance.now() - reqStartMs - (firstTokenMs || 0)) / 1000)).toFixed(2);
            const finalPromptTps = serverTimings && serverTimings.prompt_per_second
                ? serverTimings.prompt_per_second.toFixed(2)
                : null;
            const finalTokens = (serverTimings && serverTimings.predicted_n) || chunkTokenCount;
            const finalTtft = serverTimings && serverTimings.prompt_ms
                ? Math.round(serverTimings.prompt_ms)
                : Math.round(firstTokenMs || 0);

            if (liveTpsVal) liveTpsVal.textContent = finalGenTps;
            metricsBar.innerHTML = `
                <span class="m-pill m-tps" title="Velocidad real de generación de tokens"><i class="fa-solid fa-bolt"></i> <strong>${finalGenTps}</strong> t/s</span>
                ${finalPromptTps ? `<span class="m-pill" title="Velocidad de lectura del prompt"><i class="fa-solid fa-rocket"></i> Prompt: <strong>${finalPromptTps}</strong> t/s</span>` : ""}
                <span class="m-pill" title="Tiempo hasta el primer token"><i class="fa-solid fa-hourglass-start"></i> TTFT: <strong>${finalTtft}</strong> ms</span>
                <span class="m-pill"><i class="fa-solid fa-coins"></i> <strong>${finalTokens}</strong> tokens</span>
                <span class="m-pill"><i class="fa-solid fa-clock"></i> ${totalElapsedSec}s</span>
                <button type="button" class="btn-copy-reply" title="Copiar respuesta completa"><i class="fa-solid fa-copy"></i> Copiar respuesta</button>
            `;
            const copyReplyBtn = metricsBar.querySelector(".btn-copy-reply");
            if (copyReplyBtn) {
                copyReplyBtn.addEventListener("click", (e) => copyTextWithFeedback(assistantResponseText, e.currentTarget, "Copiado"));
            }

            if (assistantResponseText) {
                state.chatMessages.push({ role: "assistant", content: assistantResponseText });
            }
            
        } catch (err) {
            if (err.name === "AbortError") {
                if (assistantResponseText) {
                    assistantResponseText += "\n\n*[Generación detenida por el usuario]*";
                    bodyContainer.innerHTML = marked.parse(assistantResponseText);
                    decorateCodeBlocks(bodyContainer, true);
                    state.chatMessages.push({ role: "assistant", content: assistantResponseText });
                } else {
                    bodyContainer.innerHTML = `<span class="text-dim"><em>Generación cancelada.</em></span>`;
                }
            } else {
                console.error(err);
                bodyContainer.innerHTML = `<span style="color: var(--color-danger);"><i class="fa-solid fa-circle-exclamation"></i> Error al conectar con Llama-Server: ${err.message}.</span>`;
            }
        } finally {
            currentChatAbortController = null;
            chatInputTextarea.disabled = false;
            btnSendMessage.disabled = false;
            btnSendMessage.classList.remove("hidden");
            if (btnStopGeneration) btnStopGeneration.classList.add("hidden");
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

    const btnOpenLastCode = document.getElementById("btn-open-last-code");
    if (btnOpenLastCode) {
        btnOpenLastCode.addEventListener("click", () => switchToTab("tab-code"));
    }

    // --- CODE STUDIO CONTROLS ---
    const btnViewHighlight = document.getElementById("btn-view-mode-highlight");
    const btnViewEdit = document.getElementById("btn-view-mode-edit");
    const codeHighlightedContainer = document.getElementById("code-highlighted-container");
    const codeEditorTextarea = document.getElementById("code-editor-textarea");
    const codeFilenameInput = document.getElementById("code-filename");
    const codeLangSelect = document.getElementById("code-lang");

    function setCodeEditorMode(editMode) {
        if (!codeHighlightedContainer || !codeEditorTextarea) return;
        if (editMode) {
            btnViewEdit.classList.add("active");
            btnViewHighlight.classList.remove("active");
            codeHighlightedContainer.classList.add("hidden");
            codeEditorTextarea.classList.remove("hidden");
            codeEditorTextarea.value = activeCodeContent;
            codeEditorTextarea.focus();
        } else {
            activeCodeContent = codeEditorTextarea.value || activeCodeContent;
            btnViewHighlight.classList.add("active");
            btnViewEdit.classList.remove("active");
            codeEditorTextarea.classList.add("hidden");
            codeHighlightedContainer.classList.remove("hidden");
            openCodeInStudio(activeCodeContent, codeLangSelect ? codeLangSelect.value : "python", codeFilenameInput ? codeFilenameInput.value : "snippet.py");
        }
    }

    if (btnViewHighlight) btnViewHighlight.addEventListener("click", () => setCodeEditorMode(false));
    if (btnViewEdit) btnViewEdit.addEventListener("click", () => setCodeEditorMode(true));
    if (codeEditorTextarea) {
        codeEditorTextarea.addEventListener("input", () => {
            activeCodeContent = codeEditorTextarea.value;
            const statsInfo = document.getElementById("code-stats-info");
            if (statsInfo) {
                statsInfo.textContent = `${activeCodeContent.split("\n").length} líneas | ${new Blob([activeCodeContent]).size} bytes`;
            }
        });
    }

    const btnNewSnippet = document.getElementById("btn-new-snippet");
    if (btnNewSnippet) {
        btnNewSnippet.addEventListener("click", () => {
            openCodeInStudio("", "python", `nuevo_${Date.now().toString().slice(-4)}.py`);
            setCodeEditorMode(true);
        });
    }

    const btnCodeCopy = document.getElementById("btn-code-copy");
    if (btnCodeCopy) {
        btnCodeCopy.addEventListener("click", (e) => {
            copyTextWithFeedback(activeCodeContent, e.currentTarget, "Copiado!");
        });
    }

    const btnCodeSave = document.getElementById("btn-code-save");
    if (btnCodeSave) {
        btnCodeSave.addEventListener("click", async () => {
            const filename = (codeFilenameInput && codeFilenameInput.value.trim()) || "snippet.py";
            btnCodeSave.disabled = true;
            try {
                const res = await fetch("/api/snippets/save", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ filename, content: activeCodeContent })
                });
                const data = await res.json();
                if (data.success) {
                    const orig = btnCodeSave.innerHTML;
                    btnCodeSave.innerHTML = `<i class="fa-solid fa-check"></i> Guardado`;
                    setTimeout(() => { btnCodeSave.innerHTML = orig; }, 1800);
                    fetchSavedSnippets();
                } else {
                    alert("Error: " + data.error);
                }
            } finally {
                btnCodeSave.disabled = false;
            }
        });
    }

    const btnCodeDownload = document.getElementById("btn-code-download");
    if (btnCodeDownload) {
        btnCodeDownload.addEventListener("click", () => {
            const filename = (codeFilenameInput && codeFilenameInput.value.trim()) || "snippet.txt";
            const blob = new Blob([activeCodeContent], { type: "text/plain;charset=utf-8" });
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        });
    }

    function renderLivePreview() {
        const iframe = document.getElementById("code-live-iframe");
        if (!iframe) return;
        const lang = codeLangSelect ? codeLangSelect.value : "html";
        let htmlDoc = activeCodeContent;
        if (lang === "javascript") {
            htmlDoc = `<!DOCTYPE html><html><body style="font-family:sans-serif;background:#0f172a;color:#f8fafc;padding:16px;"><h3>Consola JS</h3><pre id="out"></pre><script>
            const log = (...a) => { document.getElementById('out').textContent += a.join(' ') + '\\n'; };
            console.log = log; console.error = log;
            try { ${activeCodeContent} } catch(e) { log('Error:', e.message); }
            <\/script></body></html>`;
        } else if (lang === "css") {
            htmlDoc = `<!DOCTYPE html><html><head><style>${activeCodeContent}</style></head><body><div class="preview">Vista previa CSS</div></body></html>`;
        }
        iframe.srcdoc = htmlDoc;
    }

    const btnCodePreviewToggle = document.getElementById("btn-code-preview-toggle");
    if (btnCodePreviewToggle) {
        btnCodePreviewToggle.addEventListener("click", () => {
            const previewPane = document.getElementById("code-preview-pane");
            if (!previewPane) return;
            previewPane.classList.toggle("hidden");
            if (!previewPane.classList.contains("hidden")) {
                renderLivePreview();
            }
        });
    }

    const btnRefreshPreview = document.getElementById("btn-refresh-preview");
    if (btnRefreshPreview) {
        btnRefreshPreview.addEventListener("click", renderLivePreview);
    }

    async function fetchSavedSnippets() {
        const listEl = document.getElementById("saved-snippets-list");
        if (!listEl) return;
        try {
            const res = await fetch("/api/snippets");
            if (!res.ok) return;
            const data = await res.json();
            const items = data.snippets || [];
            if (items.length === 0) {
                listEl.innerHTML = `<div class="empty-snippets">No hay archivos guardados en workspace_code/ todavía.</div>`;
                return;
            }
            listEl.innerHTML = "";
            items.forEach(item => {
                const row = document.createElement("div");
                row.className = "snippet-item";
                row.innerHTML = `
                    <div class="snippet-main">
                        <span class="snippet-name"><i class="fa-solid fa-file-lines"></i> ${item.name}</span>
                        <span class="snippet-meta">${item.size} B</span>
                    </div>
                    <div class="snippet-item-actions">
                        <button class="btn-icon snippet-copy-btn" title="Copiar"><i class="fa-solid fa-copy"></i></button>
                        <button class="btn-icon snippet-del-btn" title="Eliminar"><i class="fa-solid fa-trash"></i></button>
                    </div>
                `;
                row.querySelector(".snippet-main").addEventListener("click", () => {
                    const ext = item.name.split(".").pop().toLowerCase();
                    openCodeInStudio(item.content, extLangMap[ext] || "python", item.name);
                });
                row.querySelector(".snippet-copy-btn").addEventListener("click", (e) => {
                    e.stopPropagation();
                    copyTextWithFeedback(item.content, e.currentTarget, "");
                });
                row.querySelector(".snippet-del-btn").addEventListener("click", async (e) => {
                    e.stopPropagation();
                    await fetch("/api/snippets/delete", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ filename: item.name })
                    });
                    fetchSavedSnippets();
                });
                listEl.appendChild(row);
            });
        } catch (e) {
            console.error(e);
        }
    }

    const btnRefreshSavedSnippets = document.getElementById("btn-refresh-saved-snippets");
    if (btnRefreshSavedSnippets) {
        btnRefreshSavedSnippets.addEventListener("click", fetchSavedSnippets);
    }

    // --- LLAMA.CPP COMPLETE TOOLS SUITE ---
    async function fetchToolsList() {
        const selectTool = document.getElementById("select-universal-tool");
        const countSpan = document.getElementById("tools-total-count");
        if (!selectTool) return;
        try {
            const res = await fetch("/api/tools/list");
            if (!res.ok) return;
            const data = await res.json();
            if (countSpan) countSpan.textContent = data.count || 0;
            selectTool.innerHTML = "";
            (data.tools || []).forEach(t => {
                const opt = document.createElement("option");
                opt.value = t.name;
                opt.textContent = `${t.name} — ${t.description}`;
                selectTool.appendChild(opt);
            });
        } catch (e) {
            console.error("Error loading tools list:", e);
        }
    }

    function getSelectedToolsModel() {
        const sel = document.getElementById("select-tools-model");
        return (sel && sel.value) || selectServerModel.value || "";
    }

    // 1. Native C++ Multi-Thread Benchmark (llama-bench)
    const btnRunNativeBench = document.getElementById("btn-run-native-bench");
    if (btnRunNativeBench) {
        btnRunNativeBench.addEventListener("click", async () => {
            const model = getSelectedToolsModel();
            if (!model) return alert("Selecciona un modelo GGUF primero.");
            const threads = document.getElementById("tool-bench-threads").value.trim() || "1,2,4";
            const n_prompt = parseInt(document.getElementById("tool-bench-pp").value) || 128;
            const n_gen = parseInt(document.getElementById("tool-bench-tg").value) || 64;
            const outBox = document.getElementById("native-bench-results");

            btnRunNativeBench.disabled = true;
            btnRunNativeBench.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Midiendo C++...`;
            outBox.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Ejecutando <code>llama-bench -m ${model} -t ${threads}</code>... Esto toma unos 10-25 segundos.`;

            try {
                const res = await fetch("/api/tools/native-bench", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ model, threads, n_prompt, n_gen })
                });
                const data = await res.json();
                if (!data.success) {
                    outBox.textContent = "Error: " + (data.error || "Fallo en llama-bench");
                    return;
                }
                const rows = data.results || [];
                if (rows.length === 0) {
                    outBox.innerHTML = `<pre class="tool-pre-output">${data.raw_output || "Sin datos JSON"}</pre>`;
                    return;
                }
                // Find best thread count for token generation (n_gen > 0)
                let bestTg = null;
                rows.filter(r => r.n_gen > 0).forEach(r => {
                    if (!bestTg || r.avg_ts > bestTg.avg_ts) bestTg = r;
                });

                let html = `<table class="bench-compare-table">
                    <thead><tr><th>Prueba</th><th>Hilos (-t)</th><th>Tokens</th><th>Velocidad (t/s)</th></tr></thead><tbody>`;
                rows.forEach(r => {
                    const isGen = r.n_gen > 0;
                    const isWinner = bestTg && isGen && r.n_threads === bestTg.n_threads && r.avg_ts === bestTg.avg_ts;
                    html += `<tr class="${isWinner ? 'winner-row' : ''}">
                        <td>${isGen ? '⚡ Generación (tg)' : '🚀 Prompt Eval (pp)'}</td>
                        <td><strong>-t ${r.n_threads}</strong></td>
                        <td>${isGen ? r.n_gen : r.n_prompt}</td>
                        <td><strong>${Number(r.avg_ts).toFixed(2)} t/s</strong> ${isWinner ? '<span class="winner-badge">ÓPTIMO</span>' : ''}</td>
                    </tr>`;
                });
                html += `</tbody></table>`;
                if (bestTg) {
                    html += `<div class="bench-winner-Note">
                        <span><i class="fa-solid fa-trophy"></i> Mejor velocidad de generación: <strong>${Number(bestTg.avg_ts).toFixed(2)} t/s</strong> usando <strong>${bestTg.n_threads} hilos</strong>.</span>
                        <button type="button" id="btn-apply-best-threads" class="btn btn-sm btn-primary">Aplicar -t ${bestTg.n_threads} al Cluster</button>
                    </div>`;
                }
                outBox.innerHTML = html;
                const applyBtn = document.getElementById("btn-apply-best-threads");
                if (applyBtn && bestTg) {
                    applyBtn.addEventListener("click", () => {
                        if (inputThreads) inputThreads.value = bestTg.n_threads;
                        btnSaveSettings.click();
                        applyBtn.innerHTML = `<i class="fa-solid fa-check"></i> Aplicado (-t ${bestTg.n_threads})`;
                    });
                }
            } catch (e) {
                outBox.textContent = "Error ejecutando llama-bench: " + e.message;
            } finally {
                btnRunNativeBench.disabled = false;
                btnRunNativeBench.innerHTML = `<i class="fa-solid fa-bolt"></i> Medir C++`;
            }
        });
    }

    // 2. Interactive Tokenizer (llama-tokenize)
    const btnRunTokenize = document.getElementById("btn-run-tokenize");
    if (btnRunTokenize) {
        btnRunTokenize.addEventListener("click", async () => {
            const model = getSelectedToolsModel();
            const text = document.getElementById("tool-tokenize-input").value;
            const outBox = document.getElementById("tokenize-chips-output");
            const badge = document.getElementById("tokenizer-stats-badge");
            if (!model) return alert("Selecciona un modelo GGUF primero.");

            btnRunTokenize.disabled = true;
            outBox.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Tokenizando con vocabulario de ${model}...`;
            try {
                const res = await fetch("/api/tools/tokenize", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ model, text })
                });
                const data = await res.json();
                if (!data.success) {
                    outBox.textContent = "Error: " + data.error;
                    return;
                }
                const tokens = data.tokens || [];
                const ratio = tokens.length > 0 ? (text.length / tokens.length).toFixed(2) : 0;
                if (badge) badge.textContent = `${tokens.length} tokens (${ratio} chars/tok)`;
                outBox.innerHTML = tokens.map((t, idx) =>
                    `<span class="tok-chip tok-color-${idx % 5}" title="Token ID: ${t.id}">
                        <span class="tok-piece">${t.piece.replace(/</g, "&lt;").replace(/>/g, "&gt;")}</span>
                        <span class="tok-id">${t.id}</span>
                    </span>`
                ).join("");
            } catch (e) {
                outBox.textContent = "Error: " + e.message;
            } finally {
                btnRunTokenize.disabled = false;
            }
        });
    }

    // 3. GGUF Inspector, Fit-Params & Live Slots
    const inspectorOutput = document.getElementById("tool-inspector-output");
    const btnToolFitParams = document.getElementById("btn-tool-fit-params");
    if (btnToolFitParams) {
        btnToolFitParams.addEventListener("click", async () => {
            const model = getSelectedToolsModel();
            if (!model) return;
            inspectorOutput.textContent = "Calculando parámetros óptimos con llama-fit-params...";
            const res = await fetch("/api/tools/fit-params", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ model })
            });
            const data = await res.json();
            inspectorOutput.textContent = data.success
                ? `Argumentos recomendados por llama-fit-params:\n${data.recommended_flags}\n\n--- Log Completo ---\n${data.raw_output}`
                : `Error: ${data.error}`;
        });
    }

    const btnToolGgufInfo = document.getElementById("btn-tool-gguf-info");
    if (btnToolGgufInfo) {
        btnToolGgufInfo.addEventListener("click", async () => {
            const model = getSelectedToolsModel();
            if (!model) return;
            inspectorOutput.textContent = "Inspeccionando cabeceras y tensores con llama-gguf-hash...";
            const res = await fetch("/api/tools/gguf-info", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ model })
            });
            const data = await res.json();
            inspectorOutput.textContent = data.success ? data.output : `Error: ${data.error}`;
        });
    }

    const btnToolLiveSlots = document.getElementById("btn-tool-live-slots");
    if (btnToolLiveSlots) {
        btnToolLiveSlots.addEventListener("click", async () => {
            inspectorOutput.textContent = "Consultando slots activos de llama-server (/slots)...";
            const res = await fetch("/api/tools/slots");
            const data = await res.json();
            inspectorOutput.textContent = data.success
                ? JSON.stringify(data.slots, null, 2)
                : `Error: ${data.error}`;
        });
    }

    // 4. Quantizer (llama-quantize)
    const btnRunQuantize = document.getElementById("btn-run-quantize");
    if (btnRunQuantize) {
        btnRunQuantize.addEventListener("click", async () => {
            const model = getSelectedToolsModel();
            const quant_type = document.getElementById("tool-quant-type").value;
            const outPre = document.getElementById("tool-quantize-output");
            if (!model) return alert("Selecciona un modelo primero.");
            btnRunQuantize.disabled = true;
            outPre.textContent = `Cuantizando ${model} -> ${quant_type} con llama-quantize...`;
            try {
                const res = await fetch("/api/tools/quantize", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ model, quant_type })
                });
                const data = await res.json();
                outPre.textContent = data.output || data.error;
                if (data.success) fetchModels();
            } finally {
                btnRunQuantize.disabled = false;
            }
        });
    }

    // 5. Universal 47-Tool Runner
    async function runUniversalTool(forceArgs = null) {
        const tool = document.getElementById("select-universal-tool").value;
        const argsInput = document.getElementById("input-universal-args");
        const args = forceArgs !== null ? forceArgs : argsInput.value;
        const outPre = document.getElementById("universal-tool-output");
        if (!tool) return;
        outPre.textContent = `$ ./bin/${tool} ${args}\nEjecutando...`;
        try {
            const res = await fetch("/api/tools/run", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ tool, args })
            });
            const data = await res.json();
            outPre.textContent = `$ ./bin/${tool} ${args}\n\n${data.output || data.error || "(Sin salida)"}`;
        } catch (e) {
            outPre.textContent = "Error: " + e.message;
        }
    }

    const btnUniversalRun = document.getElementById("btn-universal-run");
    const btnUniversalHelp = document.getElementById("btn-universal-help");
    if (btnUniversalRun) btnUniversalRun.addEventListener("click", () => runUniversalTool(null));
    if (btnUniversalHelp) btnUniversalHelp.addEventListener("click", () => {
        document.getElementById("input-universal-args").value = "--help";
        runUniversalTool("--help");
    });

    // --- BENCHMARK PANEL ---

    btnRunBenchmark.addEventListener("click", async () => {
        if (!state.isServerRunning) {
            alert("Debes iniciar el servidor maestro antes de correr un benchmark.");
            return;
        }
        
        btnRunBenchmark.disabled = true;
        btnRunBenchmark.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Ejecutando...`;
        
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
                benchValTps.textContent = data.tokens_per_sec;
                benchValFirstToken.textContent = data.prompt_eval_ms;
                benchValTotalTime.textContent = (data.total_ms / 1000).toFixed(2);
                benchValCount.textContent = data.tokens_count;
                
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
    fetchSavedSnippets();
    fetchToolsList();
});
