/**
 * WAS-110 Monitor - Dashboard Application
 */

const state = {
    data: null,
    config: null,
    connected: false,
    theme: localStorage.getItem('theme') || 'light',
    timeRange: 24,
    charts: {},
    socket: null,
    nextRefresh: 0,
    refreshInterval: null
};

const colors = {
    temp1: { line: '#ef4444', bg: 'rgba(239, 68, 68, 0.1)' },
    temp2: { line: '#f97316', bg: 'rgba(249, 115, 22, 0.1)' },
    optical_temp: { line: '#eab308', bg: 'rgba(234, 179, 8, 0.1)' },
    voltage: { line: '#22c55e', bg: 'rgba(34, 197, 94, 0.1)' },
    bias_current: { line: '#06b6d4', bg: 'rgba(6, 182, 212, 0.1)' },
    tx_power: { line: '#8b5cf6', bg: 'rgba(139, 92, 246, 0.1)' },
    rx_power: { line: '#ec4899', bg: 'rgba(236, 72, 153, 0.1)' }
};

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    applyTheme();
    initCharts();
    setupEvents();
    connectWS();
    fetchData();
    startTimer();
});

// Theme
function applyTheme() {
    document.documentElement.setAttribute('data-theme', state.theme);
    updateChartTheme();
}

function toggleTheme() {
    state.theme = state.theme === 'light' ? 'dark' : 'light';
    localStorage.setItem('theme', state.theme);
    applyTheme();
}

function updateChartTheme() {
    const text = state.theme === 'dark' ? '#94a3b8' : '#64748b';
    const grid = state.theme === 'dark' ? '#334155' : '#e2e8f0';
    Chart.defaults.color = text;
    Chart.defaults.borderColor = grid;
    Object.values(state.charts).forEach(c => {
        if (c.options?.scales) {
            Object.values(c.options.scales).forEach(s => {
                if (s.grid) s.grid.color = grid;
                if (s.ticks) s.ticks.color = text;
            });
        }
        c.update('none');
    });
}

// Events
function setupEvents() {
    document.getElementById('theme-btn')?.addEventListener('click', toggleTheme);
    document.getElementById('refresh-btn')?.addEventListener('click', manualRefresh);
    document.getElementById('reset-alerts-btn')?.addEventListener('click', resetAlerts);
    document.getElementById('reset-zoom-btn')?.addEventListener('click', resetChartZoom);
    document.querySelectorAll('.time-btn').forEach(btn => {
        btn.addEventListener('click', e => {
            document.querySelectorAll('.time-btn').forEach(b => b.classList.remove('active'));
            e.target.classList.add('active');
            state.timeRange = parseInt(e.target.dataset.hours);
            updateCharts();
        });
    });
}

// Reset chart zoom to selected time range
function resetChartZoom() {
    const now = Date.now();
    const cutoff = now - state.timeRange * 3600000;

    Object.values(state.charts).forEach(c => {
        c.options.scales.x.min = cutoff;
        c.options.scales.x.max = now;
        if (c.options.plugins.zoom.limits) {
            c.options.plugins.zoom.limits.x.min = cutoff;
            c.options.plugins.zoom.limits.x.max = now;
        }
        c.update('none');
    });
}

// Reset alerts
async function resetAlerts() {
    if (!confirm('Clear all alerts history?')) return;
    try {
        const res = await fetch('/api/alerts/reset', { method: 'POST' });
        if (res.ok) {
            showToast('Alerts cleared');
            updateAlerts();
        } else {
            showToast('Failed to clear alerts');
        }
    } catch (e) {
        showToast('Error clearing alerts');
    }
}

// WebSocket
function connectWS() {
    try {
        state.socket = io();
        state.socket.on('data_update', data => {
            if (data.current) {
                state.data = { ...state.data, current: data.current };
                updateUI();
            }
        });
    } catch (e) {
        console.warn('WebSocket unavailable');
    }
}

// Data
async function fetchData() {
    try {
        const res = await fetch('/api/data');
        const data = await res.json();
        state.data = data;
        state.config = data.config;
        state.connected = data.current?.connected || false;
        state.nextRefresh = data.config?.fetch_interval || 60;
        updateUI();
    } catch (e) {
        state.connected = false;
        updateConnection();
    }
}

async function manualRefresh() {
    const btn = document.getElementById('refresh-btn');
    btn.classList.add('spinning');
    try {
        await fetch('/api/refresh', { method: 'POST' });
        await fetchData();
    } finally {
        btn.classList.remove('spinning');
    }
}

// Timer
function startTimer() {
    if (state.refreshInterval) clearInterval(state.refreshInterval);
    state.refreshInterval = setInterval(() => {
        state.nextRefresh--;
        if (state.nextRefresh <= 0) {
            fetchData();
            state.nextRefresh = state.config?.fetch_interval || 60;
        }
        updateTimer();
    }, 1000);
}

function updateTimer() {
    const el = document.getElementById('val-refresh');
    if (el) {
        const m = Math.floor(state.nextRefresh / 60);
        const s = state.nextRefresh % 60;
        el.textContent = m > 0 ? `${m}m ${s}s` : `${s}s`;
    }
}

// UI Updates
function updateUI() {
    updateConnection();
    updateInfo();
    updateStats();
    updateCharts();
    updateAlerts();
}

function updateConnection() {
    const el = document.getElementById('connection-badge');
    if (!el) return;
    if (state.connected) {
        el.className = 'connection-badge connected';
        el.innerHTML = '<span class="status-dot pulse"></span><span class="desktop-only">Connected</span>';
    } else {
        el.className = 'connection-badge disconnected';
        el.innerHTML = '<span class="status-dot pulse"></span><span class="desktop-only">Disconnected</span>';
    }
}

function updateInfo() {
    const c = state.data?.current;
    if (!c) return;
    setText('info-pon', c.pon_mode);
    setText('info-state', c.onu_state);
    setText('info-updated', c.last_update ? new Date(c.last_update).toLocaleTimeString() : '--');
}

function setText(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val || '--';
}

function updateStats() {
    const c = state.data?.current;
    const t = state.config?.thresholds || {};
    if (!c) return;

    setVal('temp1', c.temp1, '°C', t.temp1_warning, t.temp1_critical);
    setVal('temp2', c.temp2, '°C', t.temp2_warning, t.temp2_critical);
    setVal('optical', c.optical_temp, '°C', t.optical_temp_warning, t.optical_temp_critical);
    setVal('voltage', c.voltage, 'V');
    setVal('tx', c.tx_power, 'dBm', t.tx_power_warning, t.tx_power_critical, true);
    setVal('rx', c.rx_power, 'dBm', t.rx_power_warning, t.rx_power_critical, true);
    setVal('bias', c.bias_current, 'mA');
}

function setVal(key, val, unit, warn, crit, inverse = false) {
    const card = document.getElementById(`card-${key}`);
    const el = document.getElementById(`val-${key}`);
    if (!el) return;

    if (val !== null && val !== undefined) {
        el.innerHTML = `${val.toFixed(2)}<span class="unit">${unit}</span>`;
    } else {
        el.innerHTML = `--<span class="unit">${unit}</span>`;
    }

    if (card) {
        card.classList.remove('warning', 'critical');
        if (val !== null && warn !== undefined && crit !== undefined) {
            if (inverse) {
                if (val < crit) card.classList.add('critical');
                else if (val < warn) card.classList.add('warning');
            } else {
                if (val >= crit) card.classList.add('critical');
                else if (val >= warn) card.classList.add('warning');
            }
        }
    }
}

// Charts
function initCharts() {
    const opts = {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
            legend: { position: 'top', labels: { usePointStyle: true, padding: 10, boxWidth: 6 } },
            zoom: {
                limits: {
                    x: { min: 'original', max: 'original', minRange: 60000 } // Min 1 minute range
                },
                pan: {
                    enabled: true,
                    mode: 'x'
                },
                zoom: {
                    wheel: { enabled: true },
                    pinch: { enabled: true },
                    drag: { enabled: true, modifierKey: 'shift' },
                    mode: 'x'
                }
            }
        },
        scales: {
            x: { type: 'time', time: { displayFormats: { minute: 'HH:mm', hour: 'HH:mm', day: 'dd/MM' } }, grid: { display: false } },
            y: { beginAtZero: false }
        }
    };

    const tempEl = document.getElementById('chart-temp');
    if (tempEl) {
        state.charts.temp = new Chart(tempEl, {
            type: 'line',
            data: { datasets: [ds('CPU 0', 'temp1'), ds('CPU 1', 'temp2'), ds('Optical', 'optical_temp')] },
            options: opts
        });
    }

    const powerEl = document.getElementById('chart-power');
    if (powerEl) {
        state.charts.power = new Chart(powerEl, {
            type: 'line',
            data: { datasets: [ds('TX', 'tx_power'), ds('RX', 'rx_power')] },
            options: opts
        });
    }

    const voltEl = document.getElementById('chart-voltage');
    if (voltEl) {
        state.charts.voltage = new Chart(voltEl, {
            type: 'line',
            data: { datasets: [ds('Voltage', 'voltage')] },
            options: opts
        });
    }

    const biasEl = document.getElementById('chart-bias');
    if (biasEl) {
        state.charts.bias = new Chart(biasEl, {
            type: 'line',
            data: { datasets: [ds('Bias', 'bias_current')] },
            options: opts
        });
    }
}

function ds(label, key) {
    const c = colors[key] || { line: '#3b82f6', bg: 'rgba(59,130,246,0.1)' };
    return { label, data: [], borderColor: c.line, backgroundColor: c.bg, borderWidth: 2, fill: true, tension: 0.4, pointRadius: 0 };
}

function updateCharts() {
    const h = state.data?.history;
    if (!h || !h.timestamps.length) return;

    const now = Date.now();
    const cutoff = now - state.timeRange * 3600000;
    const idx = [];
    h.timestamps.forEach((ts, i) => {
        if (new Date(ts).getTime() >= cutoff) idx.push(i);
    });

    // Time bounds = selected time range (not data range)
    const minTime = cutoff;
    const maxTime = now;

    if (state.charts.temp) updateChart(state.charts.temp, h, idx, ['temp1', 'temp2', 'optical_temp'], minTime, maxTime);
    if (state.charts.power) updateChart(state.charts.power, h, idx, ['tx_power', 'rx_power'], minTime, maxTime);
    if (state.charts.voltage) updateChart(state.charts.voltage, h, idx, ['voltage'], minTime, maxTime);
    if (state.charts.bias) updateChart(state.charts.bias, h, idx, ['bias_current'], minTime, maxTime);
}

function updateChart(chart, h, idx, keys, minTime, maxTime) {
    keys.forEach((k, i) => {
        chart.data.datasets[i].data = idx.map(j => ({ x: new Date(h.timestamps[j]), y: h[k][j] })).filter(d => d.y !== null);
    });
    // Set zoom/pan limits to data range
    if (chart.options.plugins.zoom.limits) {
        chart.options.plugins.zoom.limits.x.min = minTime;
        chart.options.plugins.zoom.limits.x.max = maxTime;
    }
    chart.options.scales.x.min = minTime;
    chart.options.scales.x.max = maxTime;
    chart.update('none');
}

// Alerts
async function updateAlerts() {
    try {
        const res = await fetch('/api/alerts');
        const data = await res.json();
        renderAlerts(data.history || []);
    } catch (e) {}
}

function renderAlerts(alerts) {
    const el = document.getElementById('alerts-list');
    if (!el) return;
    if (!alerts.length) {
        el.innerHTML = '<div class="no-alerts">No recent alerts</div>';
        return;
    }
    const recent = alerts.slice(-10).reverse();
    el.innerHTML = recent.map(a => `
        <div class="alert-item">
            <div class="alert-badge ${a.level}">${icon(a.level)}</div>
            <div class="alert-content">
                <div class="alert-title">${a.name}</div>
                <div class="alert-message">${a.message}</div>
            </div>
            <div class="alert-time">${ago(a.timestamp)}</div>
        </div>
    `).join('');
}

function icon(l) {
    return { critical: '🔴', warning: '🟠', recovery: '🟢', info: '🔵' }[l] || '🔵';
}

function ago(ts) {
    const d = Date.now() - new Date(ts).getTime();
    if (d < 60000) return 'now';
    if (d < 3600000) return `${Math.floor(d / 60000)}m`;
    if (d < 86400000) return `${Math.floor(d / 3600000)}h`;
    return new Date(ts).toLocaleDateString();
}

// Toast
function showToast(msg, dur = 3000) {
    const t = document.getElementById('toast');
    if (t) {
        t.textContent = msg;
        t.classList.add('show');
        setTimeout(() => t.classList.remove('show'), dur);
    }
}
