/**
 * dashboard.js - Live Telemetry Poller, Metric Card Updater & Settings Manager
 */

document.addEventListener("DOMContentLoaded", () => {
  const tankSvg = document.getElementById("tank-svg");
  const visualizer = new TankVisualizer(tankSvg);

  let pollInterval = 3000;
  let pollTimer = null;
  let lastReadingId = null;

  // ---------------------------------------------------------------------------
  // 1. Live Telemetry Poller
  // ---------------------------------------------------------------------------
  async function pollCurrentStatus() {
    try {
      const res = await fetch("/api/water-level/current");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      updateDashboard(data);
    } catch (err) {
      console.warn("Telemetry polling warning:", err);
      updateConnectionStatus(false, "Connection Error");
    } finally {
      scheduleNextPoll();
    }
  }

  function scheduleNextPoll() {
    if (pollTimer) clearTimeout(pollTimer);
    const delay = document.hidden ? 30000 : 3000;
    pollTimer = setTimeout(pollCurrentStatus, delay);
  }

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      pollCurrentStatus();
    }
  });

  // ---------------------------------------------------------------------------
  // 2. Dashboard Updater
  // ---------------------------------------------------------------------------
  function updateDashboard(data) {
    const reading = data.latest_reading || {};
    const device = data.device || {};
    const settings = data.settings || {};
    const today = data.today_summary || {};
    const isOnline = data.is_online === true || device.status === "online";

    // Device status badge & header
    updateConnectionStatus(isOnline, isOnline ? "Device Online" : "Device Offline", device.last_seen);

    // If reading exists, update tank visualizer & metrics
    const pct = reading.water_percentage !== undefined ? reading.water_percentage : 0;
    const litres = reading.water_litres !== undefined ? reading.water_litres : 0;
    const capacity = settings.total_capacity_litres || 1000;
    const waterLevelCm = reading.water_level_cm !== undefined ? reading.water_level_cm : 0;
    const distanceCm = reading.distance_cm !== undefined ? reading.distance_cm : 0;
    const headroomLitres = Math.max(0, capacity - litres);
    const headroomPct = Math.max(0, 100 - pct);

    // Check if level is rising (filling)
    let isFilling = false;
    if (lastReadingId && reading.id && reading.id !== lastReadingId) {
      // compare
    }
    lastReadingId = reading.id;

    // SVG Tank visualizer
    visualizer.update({
      percentage: pct,
      litres: litres,
      capacity: capacity,
      water_level_cm: waterLevelCm,
      isFilling: isFilling,
    });

    // Metric Cards
    document.getElementById("card-pct").textContent = `${pct.toFixed(1)}%`;
    const bar = document.getElementById("card-pct-bar");
    if (bar) {
      bar.style.width = `${pct}%`;
      bar.style.backgroundColor = pct < 20 ? "var(--color-critical)" : pct <= 50 ? "var(--color-low)" : "var(--color-normal)";
    }
    document.getElementById("card-pct-sub").textContent = data.level_state ? data.level_state.replace("_", " ").toUpperCase() : "NORMAL";

    document.getElementById("card-litres").textContent = `${Math.round(litres).toLocaleString()} L`;
    document.getElementById("card-capacity").textContent = `Capacity: ${Math.round(capacity).toLocaleString()} L`;
    document.getElementById("card-height").textContent = `Depth: ${waterLevelCm.toFixed(1)} cm`;

    document.getElementById("card-headroom").textContent = `${Math.round(headroomLitres).toLocaleString()} L`;
    document.getElementById("card-headroom-pct").textContent = `${headroomPct.toFixed(1)}% available`;
    document.getElementById("card-distance").textContent = `Air Gap: ${distanceCm.toFixed(1)} cm`;

    document.getElementById("card-device-status").textContent = isOnline ? "Online" : "Offline";
    document.getElementById("card-device-id").textContent = `ID: ${device.device_id || "esp32_tank_01"}`;
    document.getElementById("card-ping-time").textContent = device.last_seen ? `Ping: ${formatRelativeTime(device.last_seen)}` : "No ping yet";

    // Today's summary
    document.getElementById("today-date-badge").textContent = today.date || new Date().toISOString().split("T")[0];
    document.getElementById("summary-min").textContent = today.min_level_percent !== null && today.min_level_percent !== undefined ? `${today.min_level_percent}%` : "--%";
    document.getElementById("summary-min-time").textContent = today.min_time ? today.min_time.split("T")[1]?.substring(0, 5) || today.min_time : "--:--";

    document.getElementById("summary-max").textContent = today.max_level_percent !== null && today.max_level_percent !== undefined ? `${today.max_level_percent}%` : "--%";
    document.getElementById("summary-max-time").textContent = today.max_time ? today.max_time.split("T")[1]?.substring(0, 5) || today.max_time : "--:--";

    document.getElementById("summary-avg").textContent = today.avg_level_percent !== null && today.avg_level_percent !== undefined ? `${today.avg_level_percent}%` : "--%";

    const netL = today.net_water_change_litres;
    if (netL !== null && netL !== undefined) {
      document.getElementById("summary-net").textContent = `${netL >= 0 ? "+" : ""}${netL} L`;
      document.getElementById("summary-net-desc").textContent = netL >= 0 ? "▲ Inflow dominant" : "▼ Outflow dominant";
    } else {
      document.getElementById("summary-net").textContent = "-- L";
      document.getElementById("summary-net-desc").textContent = "--";
    }
  }

  function updateConnectionStatus(isOnline, statusText, lastSeen) {
    const dot = document.getElementById("status-dot");
    const text = document.getElementById("device-status-text");
    const lastSeenEl = document.getElementById("last-seen-text");

    if (dot) {
      dot.className = `status-indicator ${isOnline ? "online" : ""}`;
    }
    if (text) {
      text.textContent = statusText;
    }
    if (lastSeenEl) {
      lastSeenEl.textContent = lastSeen ? `Last ping: ${formatRelativeTime(lastSeen)}` : "Last ping: --";
    }
  }

  function formatRelativeTime(dateStr) {
    if (!dateStr) return "--";
    try {
      const d = new Date(dateStr.endsWith("Z") ? dateStr : dateStr + "Z");
      const diffSec = Math.floor((new Date() - d) / 1000);
      if (isNaN(diffSec) || diffSec < 0) return dateStr.split("T")[1]?.substring(0, 5) || dateStr;
      if (diffSec < 60) return `${diffSec}s ago`;
      if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
      return `${Math.floor(diffSec / 3600)}h ago`;
    } catch {
      return dateStr;
    }
  }

  // ---------------------------------------------------------------------------
  // 3. Settings Modal
  // ---------------------------------------------------------------------------
  const modal = document.getElementById("settings-modal");
  const btnOpen = document.getElementById("btn-open-settings");
  const btnClose = document.getElementById("btn-close-settings");
  const btnCancel = document.getElementById("btn-cancel-settings");
  const formSettings = document.getElementById("settings-form");

  async function openSettings() {
    try {
      const res = await fetch("/api/settings");
      if (res.ok) {
        const data = await res.json();
        const s = data.settings || {};
        document.getElementById("set-height").value = s.tank_height_cm || 200;
        document.getElementById("set-offset").value = s.sensor_offset_cm || 15;
        document.getElementById("set-capacity").value = s.total_capacity_litres || 1000;
        document.getElementById("set-timeout").value = s.offline_timeout_seconds || 300;
        document.getElementById("set-low").value = s.low_threshold_percent || 20;
        document.getElementById("set-crit").value = s.critical_low_threshold_percent || 10;
      }
    } catch (e) {
      console.error(e);
    }
    if (modal) modal.style.display = "flex";
  }

  function closeSettings() {
    if (modal) modal.style.display = "none";
  }

  if (btnOpen) btnOpen.addEventListener("click", openSettings);
  if (btnClose) btnClose.addEventListener("click", closeSettings);
  if (btnCancel) btnCancel.addEventListener("click", closeSettings);

  if (formSettings) {
    formSettings.addEventListener("submit", async (e) => {
      e.preventDefault();
      const payload = {
        tank_height_cm: parseFloat(document.getElementById("set-height").value),
        sensor_offset_cm: parseFloat(document.getElementById("set-offset").value),
        total_capacity_litres: parseFloat(document.getElementById("set-capacity").value),
        offline_timeout_seconds: parseInt(document.getElementById("set-timeout").value, 10),
        low_threshold_percent: parseFloat(document.getElementById("set-low").value),
        critical_low_threshold_percent: parseFloat(document.getElementById("set-crit").value),
      };

      try {
        const res = await fetch("/api/settings", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (res.ok) {
          closeSettings();
          if (window.showToast) window.showToast("Settings updated successfully!");
          pollCurrentStatus();
        } else {
          const err = await res.json();
          alert(`Error saving settings: ${err.error || "Failed"}`);
        }
      } catch (err) {
        alert("Failed to save settings");
      }
    });
  }

  // ---------------------------------------------------------------------------
  // 4. Initial Kickoff
  // ---------------------------------------------------------------------------
  pollCurrentStatus();
  if (window.initAnalytics) {
    window.initAnalytics();
  }
});

