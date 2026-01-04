/**
 * WAS-110 Monitor - Dashboard Application
 */

// State
let state = {
    data: null,
    config: null,
    connected: false,
    theme: localStorage.getItem('theme') || 'light',
    timeRange: 3,  // hours
    charts: {},
    socket: null,
    nextRefresh: 0,
    refreshInterval: null
};

// Chart colors
const chartColors = {
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
    setupEventListeners();
    connectWebSocket();
    fetchData();
    startRefreshTimer();
});

// Theme handling
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
    const textColor = state.theme === 'dark' ? '#94a3b8' : '#64748b';
    const gridColor = state.theme === 'dark' ? '#334155' : '#e2e8f0';

    Chart.defaults.color = textColor;
    Chart.defaults.borderColor = gridColor;

    // Update existing charts
    Object.values(state.charts).forEach(chart => {
        if (chart.options.scales) {
            Object.values(chart.options.scales).forEach(scale => {
                scale.grid.color = gridColor;
                scale.ticks.color = textColor;
            });
        }
        chart.update('none');
    });
}

// Event listeners
function setupEventListeners() {
    document.getElementById('theme-toggle').addEventListener('click', toggleTheme);
    document.getElementById('refresh-btn').addEventListener('click', manualRefresh);

    // Time range buttons
    document.querySelectorAll('.time-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            document.querySelectorAll('.time-btn').forEach(b => b.classList.remove('active'));
            e.target.classList.add('active');
            state.timeRange = parseInt(e.target.dataset.hours);
            updateCharts();
        });
    });
}

// WebSocket connection
function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}`;

    try {
        state.socket = io(wsUrl);

        state.socket.on('connect', () => {
            console.log('WebSocket connected');
        });

        state.socket.on('data_update', (data) => {
            console.log('Received data update');
            if (data.current) {
                state.data = { ...state.data, current: data.current };
                updateUI();
            }
        });

        state.socket.on('disconnect', () => {
            console.log('WebSocket disconnected');
        });
    } catch (e) {
        console.warn('WebSocket not available, falling back to polling');
    }
}

// Data fetching
async function fetchData() {
    try {
        const response = await fetch('/api/data');
        const data = await response.json();
        state.data = data;
        state.config = data.config;
        state.connected = data.current?.connected || false;
        state.nextRefresh = data.config?.fetch_interval || 60;
        updateUI();
    } catch (error) {
        console.error('Failed to fetch data:', error);
        state.connected = false;
        updateConnectionStatus();
    }
}

async function manualRefresh() {
    const btn = document.getElementById('refresh-btn');
    btn.disabled = true;
    btn.classList.add('spinning');

    try {
        const response = await fetch('/api/refresh', { method: 'POST' });
        const data = await response.json();
        if (data.success) {
            await fetchData();
        }
    } catch (error) {
        console.error('Refresh failed:', error);
    } finally {
        btn.disabled = false;
        btn.classList.remove('spinning');
    }
}

// Refresh timer
function startRefreshTimer() {
    if (state.refreshInterval) {
        clearInterval(state.refreshInterval);
    }

    state.refreshInterval = setInterval(() => {
        state.nextRefresh--;
        if (state.nextRefresh <= 0) {
            fetchData();
            state.nextRefresh = state.config?.fetch_interval || 60;
        }
        updateRefreshTimer();
    }, 1000);
}

function updateRefreshTimer() {
    const timerEl = document.getElementById('next-refresh');
    if (timerEl) {
        const minutes = Math.floor(state.nextRefresh / 60);
        const seconds = state.nextRefresh % 60;
        timerEl.textContent = minutes > 0
            ? `${minutes}m ${seconds}s`
            : `${seconds}s`;
    }
}

// UI Updates
function updateUI() {
    updateConnectionStatus();
    updateSystemInfo();
    updateStatCards();
    updateCharts();
    updateAlerts();
}

function updateConnectionStatus() {
    const statusEl = document.getElementById('connection-status');
    if (state.connected) {
        statusEl.className = 'connection-status connected';
        statusEl.innerHTML = '<span class="status-dot"></span> Connected';
    } else {
        statusEl.className = 'connection-status disconnected';
        statusEl.innerHTML = '<span class="status-dot"></span> Disconnected';
    }
}

function updateSystemInfo() {
    const current = state.data?.current;
    if (!current) return;

    document.getElementById('info-uptime').textContent = current.uptime || '--';
    document.getElementById('info-firmware').textContent = current.firmware || '--';
    document.getElementById('info-pon').textContent = current.pon_mode || '--';
    document.getElementById('info-onu-state').textContent = current.onu_state || '--';
    document.getElementById('info-last-update').textContent = current.last_update
        ? new Date(current.last_update).toLocaleTimeString()
        : '--';
}

function updateStatCards() {
    const current = state.data?.current;
    const thresholds = state.config?.thresholds;
    if (!current) return;

    // Temperature cards
    updateStatCard('temp1', current.temp1, '°C', thresholds?.temp_warning, thresholds?.temp_critical);
    updateStatCard('temp2', current.temp2, '°C', thresholds?.temp_warning, thresholds?.temp_critical);
    updateStatCard('optical-temp', current.optical_temp, '°C', thresholds?.optical_temp_warning, thresholds?.optical_temp_critical);

    // Other metrics
    updateStatCard('voltage', current.voltage, 'V');
    updateStatCard('bias-current', current.bias_current, 'mA');
    updateStatCard('tx-power', current.tx_power, 'dBm', thresholds?.tx_power_warning, thresholds?.tx_power_critical, true);
    updateStatCard('rx-power', current.rx_power, 'dBm', thresholds?.rx_power_warning, thresholds?.rx_power_critical, true);
}

function updateStatCard(id, value, unit, warning = null, critical = null, inverse = false) {
    const card = document.getElementById(`stat-${id}`);
    const valueEl = document.getElementById(`value-${id}`);

    if (!card || !valueEl) return;

    // Update value
    if (value !== null && value !== undefined) {
        valueEl.innerHTML = `${value.toFixed(2)}<span class="unit">${unit}</span>`;
    } else {
        valueEl.innerHTML = `--<span class="unit">${unit}</span>`;
    }

    // Update status classes
    card.classList.remove('warning', 'critical');
    if (value !== null && warning !== null && critical !== null) {
        if (inverse) {
            // For power levels (lower is worse)
            if (value < critical) card.classList.add('critical');
            else if (value < warning) card.classList.add('warning');
        } else {
            // For temperatures (higher is worse)
            if (value >= critical) card.classList.add('critical');
            else if (value >= warning) card.classList.add('warning');
        }
    }
}

// Charts
function initCharts() {
    const commonOptions = {
        responsive: true,
        maintainAspectRatio: false,
        interaction: {
            mode: 'index',
            intersect: false,
        },
        plugins: {
            legend: {
                position: 'top',
                labels: {
                    usePointStyle: true,
                    padding: 15
                }
            },
            tooltip: {
                backgroundColor: state.theme === 'dark' ? '#1e293b' : '#ffffff',
                titleColor: state.theme === 'dark' ? '#f1f5f9' : '#1a1a2e',
                bodyColor: state.theme === 'dark' ? '#94a3b8' : '#64748b',
                borderColor: state.theme === 'dark' ? '#334155' : '#e2e8f0',
                borderWidth: 1,
                cornerRadius: 8,
                padding: 12
            }
        },
        scales: {
            x: {
                type: 'time',
                time: {
                    displayFormats: {
                        minute: 'HH:mm',
                        hour: 'HH:mm'
                    }
                },
                grid: {
                    display: false
                }
            },
            y: {
                beginAtZero: false,
                grid: {
                    color: state.theme === 'dark' ? '#334155' : '#e2e8f0'
                }
            }
        }
    };

    // Temperature chart
    state.charts.temperature = new Chart(document.getElementById('chart-temperature'), {
        type: 'line',
        data: {
            datasets: [
                createDataset('CPU 0', 'temp1'),
                createDataset('CPU 1', 'temp2'),
                createDataset('Optical', 'optical_temp')
            ]
        },
        options: {
            ...commonOptions,
            scales: {
                ...commonOptions.scales,
                y: {
                    ...commonOptions.scales.y,
                    title: { display: true, text: 'Temperature (°C)' }
                }
            }
        }
    });

    // Voltage chart
    state.charts.voltage = new Chart(document.getElementById('chart-voltage'), {
        type: 'line',
        data: {
            datasets: [createDataset('Supply Voltage', 'voltage')]
        },
        options: {
            ...commonOptions,
            scales: {
                ...commonOptions.scales,
                y: {
                    ...commonOptions.scales.y,
                    title: { display: true, text: 'Voltage (V)' }
                }
            }
        }
    });

    // Bias current chart
    state.charts.bias = new Chart(document.getElementById('chart-bias'), {
        type: 'line',
        data: {
            datasets: [createDataset('Bias Current', 'bias_current')]
        },
        options: {
            ...commonOptions,
            scales: {
                ...commonOptions.scales,
                y: {
                    ...commonOptions.scales.y,
                    title: { display: true, text: 'Current (mA)' }
                }
            }
        }
    });

    // Optical power chart
    state.charts.power = new Chart(document.getElementById('chart-power'), {
        type: 'line',
        data: {
            datasets: [
                createDataset('TX Power', 'tx_power'),
                createDataset('RX Power', 'rx_power')
            ]
        },
        options: {
            ...commonOptions,
            scales: {
                ...commonOptions.scales,
                y: {
                    ...commonOptions.scales.y,
                    title: { display: true, text: 'Power (dBm)' }
                }
            }
        }
    });
}

function createDataset(label, key) {
    const colors = chartColors[key] || { line: '#3b82f6', bg: 'rgba(59, 130, 246, 0.1)' };
    return {
        label: label,
        data: [],
        borderColor: colors.line,
        backgroundColor: colors.bg,
        borderWidth: 2,
        fill: true,
        tension: 0.4,
        pointRadius: 0,
        pointHoverRadius: 4
    };
}

function updateCharts() {
    if (!state.data?.history) return;

    const history = state.data.history;
    const cutoffTime = Date.now() - (state.timeRange * 60 * 60 * 1000);

    // Filter data by time range
    const filteredIndices = [];
    history.timestamps.forEach((ts, i) => {
        const time = new Date(ts).getTime();
        if (time >= cutoffTime) {
            filteredIndices.push(i);
        }
    });

    // Update temperature chart
    updateChartData(state.charts.temperature, history, filteredIndices, ['temp1', 'temp2', 'optical_temp']);

    // Update voltage chart
    updateChartData(state.charts.voltage, history, filteredIndices, ['voltage']);

    // Update bias chart
    updateChartData(state.charts.bias, history, filteredIndices, ['bias_current']);

    // Update power chart
    updateChartData(state.charts.power, history, filteredIndices, ['tx_power', 'rx_power']);
}

function updateChartData(chart, history, indices, keys) {
    keys.forEach((key, datasetIndex) => {
        const data = indices.map(i => ({
            x: new Date(history.timestamps[i]),
            y: history[key][i]
        })).filter(d => d.y !== null);

        chart.data.datasets[datasetIndex].data = data;
    });

    chart.update('none');
}

// Alerts
async function updateAlerts() {
    try {
        const response = await fetch('/api/alerts');
        const data = await response.json();
        renderAlerts(data.history || []);
    } catch (error) {
        console.error('Failed to fetch alerts:', error);
    }
}

function renderAlerts(alerts) {
    const container = document.getElementById('alerts-list');
    if (!container) return;

    if (alerts.length === 0) {
        container.innerHTML = '<div class="no-alerts">No recent alerts</div>';
        return;
    }

    // Show last 10 alerts, most recent first
    const recentAlerts = alerts.slice(-10).reverse();

    container.innerHTML = recentAlerts.map(alert => `
        <div class="alert-item">
            <div class="alert-icon ${alert.level}">
                ${getAlertIcon(alert.level)}
            </div>
            <div class="alert-content">
                <div class="alert-title">${alert.name}</div>
                <div class="alert-message">${alert.message}</div>
            </div>
            <div class="alert-time">${formatTime(alert.timestamp)}</div>
        </div>
    `).join('');
}

function getAlertIcon(level) {
    const icons = {
        critical: '⚠️',
        warning: '⚡',
        recovery: '✅',
        info: 'ℹ️'
    };
    return icons[level] || icons.info;
}

function formatTime(timestamp) {
    const date = new Date(timestamp);
    const now = new Date();
    const diff = now - date;

    if (diff < 60000) return 'Just now';
    if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
    return date.toLocaleDateString();
}
