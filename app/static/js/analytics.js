/**
 * analytics.js - 15-Day History Trends, Day Comparison, and Backup Manager
 */

let analyticsChartInstance = null;
let comparisonChartInstance = null;

function showToast(message, duration = 3500) {
  const toast = document.getElementById("toast");
  if (!toast) return;
  toast.textContent = message;
  toast.classList.add("show");
  setTimeout(() => toast.classList.remove("show"), duration);
}

// -----------------------------------------------------------------------------
// 1. Tab Navigation
// -----------------------------------------------------------------------------
function initTabs() {
  const tabs = document.querySelectorAll(".tab-btn");
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      tabs.forEach((t) => t.classList.remove("active"));
      document.querySelectorAll(".tab-content").forEach((c) => c.classList.remove("active"));

      tab.classList.add("active");
      const targetId = tab.getAttribute("data-tab");
      const targetContent = document.getElementById(targetId);
      if (targetContent) targetContent.classList.add("active");

      if (targetId === "tab-backup") {
        loadBackupLogs();
      } else if (targetId === "tab-compare") {
        if (!document.getElementById("compare-date1").value) {
          initComparisonDates();
        }
      }
    });
  });
}

// -----------------------------------------------------------------------------
// 2. 15-Day History & Analytics Chart
// -----------------------------------------------------------------------------
async function loadHistoryForDate(dateStr, deviceId) {
  try {
    let url = `/api/history/readings?date=${encodeURIComponent(dateStr)}`;
    const dev = deviceId || localStorage.getItem("selected_device_id");
    if (dev) {
      url += `&device_id=${encodeURIComponent(dev)}`;
    }
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    renderAnalyticsChart(data.date, data.readings || []);
  } catch (err) {
    console.error("Error loading historical readings:", err);
  }
}

window.loadHistoryForDate = loadHistoryForDate;

function renderAnalyticsChart(dateStr, readings) {
  const canvas = document.getElementById("analytics-chart");
  if (!canvas || typeof Chart === "undefined") return;

  const labels = readings.map((r) => {
    const ts = r.timestamp || "";
    return ts.includes("T") ? ts.split("T")[1].substring(0, 5) : ts.split(" ")[1]?.substring(0, 5) || ts;
  });
  const pcts = readings.map((r) => r.water_percentage);
  const litres = readings.map((r) => r.water_litres);

  // Update summary bar
  const minVal = pcts.length ? Math.min(...pcts) : 0;
  const maxVal = pcts.length ? Math.max(...pcts) : 0;
  const avgVal = pcts.length ? (pcts.reduce((a, b) => a + b, 0) / pcts.length) : 0;

  document.getElementById("hist-min").textContent = `${minVal.toFixed(1)}%`;
  document.getElementById("hist-max").textContent = `${maxVal.toFixed(1)}%`;
  document.getElementById("hist-avg").textContent = `${avgVal.toFixed(1)}%`;
  document.getElementById("hist-count").textContent = pcts.length;

  if (analyticsChartInstance) {
    analyticsChartInstance.destroy();
  }

  const ctx = canvas.getContext("2d");
  const gradient = ctx.createLinearGradient(0, 0, 0, 300);
  gradient.addColorStop(0, "rgba(6, 182, 212, 0.4)");
  gradient.addColorStop(1, "rgba(6, 182, 212, 0.0)");

  analyticsChartInstance = new Chart(ctx, {
    type: "line",
    data: {
      labels: labels,
      datasets: [
        {
          label: `Water Level % (${dateStr})`,
          data: pcts,
          borderColor: "#06b6d4",
          backgroundColor: gradient,
          fill: true,
          tension: 0.3,
          pointRadius: labels.length > 50 ? 0 : 3,
          borderWidth: 2,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: {
          grid: { color: "rgba(51, 65, 85, 0.4)" },
          ticks: { color: "#94a3b8", maxTicksLimit: 12 },
        },
        y: {
          min: 0,
          max: 100,
          grid: { color: "rgba(51, 65, 85, 0.4)" },
          ticks: { color: "#94a3b8", callback: (v) => `${v}%` },
        },
      },
      plugins: {
        legend: { labels: { color: "#94a3b8" } },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const idx = ctx.dataIndex;
              const lit = litres[idx] !== undefined ? ` | ${litres[idx]} L` : "";
              return `Level: ${ctx.parsed.y}%${lit}`;
            },
          },
        },
      },
    },
  });
}

function initDatePickers() {
  const picker = document.getElementById("history-date-picker");
  const today = new Date().toISOString().split("T")[0];
  if (picker) {
    picker.value = today;
    picker.max = today;
    picker.addEventListener("change", (e) => {
      loadHistoryForDate(e.target.value);
    });
  }

  const quickPills = document.querySelectorAll(".pill-btn");
  quickPills.forEach((pill) => {
    pill.addEventListener("click", () => {
      quickPills.forEach((p) => p.classList.remove("active"));
      pill.classList.add("active");
      const range = pill.getAttribute("data-range");
      const d = new Date();
      if (range === "yesterday") {
        d.setDate(d.getDate() - 1);
      }
      const iso = d.toISOString().split("T")[0];
      if (picker) picker.value = iso;
      loadHistoryForDate(iso);
    });
  });
}

// -----------------------------------------------------------------------------
// 3. Day-to-Day Comparison
// -----------------------------------------------------------------------------
function initComparisonDates() {
  const d1 = document.getElementById("compare-date1");
  const d2 = document.getElementById("compare-date2");
  const today = new Date();
  const yesterday = new Date();
  yesterday.setDate(yesterday.getDate() - 1);

  if (d1) d1.value = today.toISOString().split("T")[0];
  if (d2) d2.value = yesterday.toISOString().split("T")[0];

  const btn = document.getElementById("btn-run-compare");
  if (btn) {
    btn.addEventListener("click", runComparison);
  }
}

async function runComparison() {
  const date1 = document.getElementById("compare-date1").value;
  const date2 = document.getElementById("compare-date2").value;
  if (!date1 || !date2) {
    showToast("Please select two dates to compare");
    return;
  }

  try {
    const res = await fetch(`/api/history/compare?date1=${encodeURIComponent(date1)}&date2=${encodeURIComponent(date2)}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    renderComparisonView(data);
  } catch (err) {
    console.error("Comparison error:", err);
    showToast("Failed to fetch day-to-day comparison");
  }
}

function renderComparisonView(data) {
  const s1 = data.date1_stats || {};
  const s2 = data.date2_stats || {};
  const d = data.differences || {};

  document.getElementById("cmp-avg1").textContent = `${s1.avg_level_percent || 0}%`;
  document.getElementById("cmp-avg2").textContent = `${s2.avg_level_percent || 0}%`;
  document.getElementById("cmp-avg-delta").textContent = `${d.avg_level_difference >= 0 ? "+" : ""}${d.avg_level_difference || 0}%`;

  document.getElementById("cmp-min1").textContent = `${s1.min_level_percent || 0}%`;
  document.getElementById("cmp-min2").textContent = `${s2.min_level_percent || 0}%`;
  document.getElementById("cmp-min-delta").textContent = `${d.min_level_difference >= 0 ? "+" : ""}${d.min_level_difference || 0}%`;

  document.getElementById("cmp-max1").textContent = `${s1.max_level_percent || 0}%`;
  document.getElementById("cmp-max2").textContent = `${s2.max_level_percent || 0}%`;
  document.getElementById("cmp-max-delta").textContent = `${d.max_level_difference >= 0 ? "+" : ""}${d.max_level_difference || 0}%`;

  const canvas = document.getElementById("comparison-chart");
  if (!canvas || typeof Chart === "undefined") return;

  const r1 = data.date1_readings || [];
  const r2 = data.date2_readings || [];

  const labels = Array.from(new Set([
    ...r1.map((r) => r.timestamp ? r.timestamp.split("T")[1]?.substring(0, 5) || r.timestamp : ""),
    ...r2.map((r) => r.timestamp ? r.timestamp.split("T")[1]?.substring(0, 5) || r.timestamp : "")
  ])).filter(Boolean).sort();

  if (comparisonChartInstance) comparisonChartInstance.destroy();

  const ctx = canvas.getContext("2d");
  comparisonChartInstance = new Chart(ctx, {
    type: "line",
    data: {
      labels: labels,
      datasets: [
        {
          label: `${data.date1} (Primary)`,
          data: r1.map((r) => r.water_percentage),
          borderColor: "#06b6d4",
          backgroundColor: "rgba(6, 182, 212, 0.1)",
          tension: 0.3,
          borderWidth: 2,
        },
        {
          label: `${data.date2} (Baseline)`,
          data: r2.map((r) => r.water_percentage),
          borderColor: "#f59e0b",
          borderDash: [6, 4],
          backgroundColor: "rgba(245, 158, 11, 0.1)",
          tension: 0.3,
          borderWidth: 2,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: { grid: { color: "rgba(51, 65, 85, 0.4)" }, ticks: { color: "#94a3b8" } },
        y: { min: 0, max: 100, grid: { color: "rgba(51, 65, 85, 0.4)" }, ticks: { color: "#94a3b8", callback: (v) => `${v}%` } },
      },
      plugins: { legend: { labels: { color: "#94a3b8" } } },
    },
  });
}

// -----------------------------------------------------------------------------
// 4. Backup Management
// -----------------------------------------------------------------------------
async function loadBackupLogs() {
  const tbody = document.getElementById("backup-table-body");
  if (!tbody) return;

  try {
    const res = await fetch("/api/backup/list");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const backups = data.backups || [];

    if (!backups.length) {
      tbody.innerHTML = `<tr><td colspan="7" class="text-center">No backups found yet. Click "Create Manual Backup" above.</td></tr>`;
      return;
    }

    tbody.innerHTML = backups
      .map(
        (b) => `
      <tr>
        <td>${b.created_at || "--"}</td>
        <td><code>${b.filename}</code></td>
        <td><span class="badge">${b.file_format ? b.file_format.toUpperCase() : "CSV"}</span></td>
        <td>${b.backup_type || "manual"}</td>
        <td>${b.record_count ? b.record_count.toLocaleString() : "--"}</td>
        <td>${b.file_size_bytes ? (b.file_size_bytes / 1024).toFixed(1) + " KB" : "--"}</td>
        <td>
          <a href="/api/backup/download/${encodeURIComponent(b.filename)}" class="btn btn-secondary btn-sm" download>
            ⬇ Download
          </a>
        </td>
      </tr>
    `
      )
      .join("");
  } catch (err) {
    console.error("Error loading backups:", err);
    tbody.innerHTML = `<tr><td colspan="7" class="text-center">Error loading backup logs</td></tr>`;
  }
}

function initBackupControls() {
  const btn = document.getElementById("btn-create-backup");
  if (btn) {
    btn.addEventListener("click", async () => {
      const format = document.getElementById("backup-format-select").value || "both";
      btn.disabled = true;
      btn.textContent = "⏳ Generating...";

      try {
        const res = await fetch("/api/backup/create", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ format }),
        });
        const data = await res.json();
        if (res.ok) {
          showToast(`Backup created: ${data.filename || "success"}`);
          loadBackupLogs();
        } else {
          showToast(`Backup error: ${data.error || "Failed"}`);
        }
      } catch (err) {
        showToast("Failed to create backup");
      } finally {
        btn.disabled = false;
        btn.textContent = "⬇ Create Manual Backup";
      }
    });
  }
}

window.initAnalytics = function () {
  initTabs();
  initDatePickers();
  initBackupControls();
  const today = new Date().toISOString().split("T")[0];
  loadHistoryForDate(today);
};

