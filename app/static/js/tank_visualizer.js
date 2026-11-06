/**
 * tank_visualizer.js - SVG Dynamic Fluid Tank Controller
 */

class TankVisualizer {
  constructor(svgElement) {
    this.svg = svgElement;
    this.liquidBody = svgElement.querySelector("#liquid-body");
    this.waveContainer = svgElement.querySelector("#wave-container");
    this.textPct = svgElement.querySelector("#tank-text-pct");
    this.textLitres = svgElement.querySelector("#tank-text-litres");
    this.textHeight = svgElement.querySelector("#tank-text-height");
    this.inflowStream = svgElement.querySelector("#inflow-stream");
    this.badgeFilling = svgElement.querySelector("#tank-badge-filling");
    this.stateBadge = document.getElementById("tank-state-badge");

    // Physical bounds inside SVG (viewBox 0 0 240 320)
    this.TANK_TOP_Y = 30;
    this.TANK_HEIGHT = 250;
    this.TANK_BOTTOM_Y = 280;
  }

  update({ percentage, litres, capacity, water_level_cm, isFilling = false }) {
    const pct = Math.max(0, Math.min(100, Number(percentage) || 0));
    const fillHeight = (pct / 100) * this.TANK_HEIGHT;
    const targetY = this.TANK_BOTTOM_Y - fillHeight;

    // 1. Update liquid dimensions and wave position
    if (this.liquidBody) {
      this.liquidBody.setAttribute("y", targetY);
      this.liquidBody.setAttribute("height", fillHeight);
    }
    if (this.waveContainer) {
      this.waveContainer.setAttribute("transform", `translate(0, ${targetY})`);
    }

    // 2. Determine color gradient & state badge
    let gradUrl = "url(#grad-normal)";
    let stateLabel = "Normal";
    let stateClass = "normal";

    if (isFilling) {
      gradUrl = "url(#grad-filling)";
      stateLabel = "Filling";
      stateClass = "filling";
    } else if (pct < 20) {
      gradUrl = "url(#grad-critical)";
      stateLabel = "Critically Low";
      stateClass = "critical";
    } else if (pct <= 50) {
      gradUrl = "url(#grad-low)";
      stateLabel = "Low Warning";
      stateClass = "low";
    }

    if (this.liquidBody) {
      this.liquidBody.setAttribute("fill", gradUrl);
    }

    if (this.stateBadge) {
      this.stateBadge.textContent = stateLabel;
      this.stateBadge.className = `badge ${stateClass}`;
    }

    // 3. Update overlay readouts
    if (this.textPct) {
      this.textPct.textContent = `${pct.toFixed(1)}%`;
    }
    if (this.textLitres) {
      const cap = capacity ? Math.round(capacity).toLocaleString() : "--";
      const lit = litres !== undefined && litres !== null ? Math.round(litres).toLocaleString() : "--";
      this.textLitres.textContent = `${lit} L / ${cap} L`;
    }
    if (this.textHeight) {
      const h = Number(water_level_cm) || 0;
      this.textHeight.textContent = `${h.toFixed(1)} cm depth`;
    }

    // 4. Inflow animations
    if (isFilling) {
      this.svg.classList.add("is-filling");
      if (this.inflowStream) this.inflowStream.setAttribute("opacity", "1");
      if (this.badgeFilling) this.badgeFilling.setAttribute("opacity", "1");
    } else {
      this.svg.classList.remove("is-filling");
      if (this.inflowStream) this.inflowStream.setAttribute("opacity", "0");
      if (this.badgeFilling) this.badgeFilling.setAttribute("opacity", "0");
    }

    return { pct, stateClass, stateLabel };
  }
}

window.TankVisualizer = TankVisualizer;

