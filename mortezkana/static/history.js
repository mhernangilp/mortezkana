(() => {
  "use strict";
  const root = document.getElementById("score-history");
  if (!root) return;
  const history = JSON.parse(root.dataset.history);
  const plot = document.getElementById("history-plot");
  const selector = document.getElementById("history-step");
  const legend = document.getElementById("history-legend");
  const detail = document.getElementById("history-detail");
  const colors = ["#28624c", "#b64525", "#315d9b", "#853e8b", "#95710b", "#167a89", "#bf3666", "#6056b2", "#5c721b", "#755142"];
  const number = new Intl.NumberFormat("es-ES");
  const axisNumber = new Intl.NumberFormat("es-ES", {notation: "compact", maximumFractionDigits: 1});
  let view = "people";
  let step = history.challenges.length;
  const hidden = {people: new Set(), teams: new Set()};
  let geometry;

  function svgElement(tag, attributes = {}, text) {
    const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, String(value));
    if (text !== undefined) node.textContent = text;
    return node;
  }

  const labels = ["Inicio", ...history.challenges.map(challenge => `${challenge.chronology_position}. ${challenge.name}`)];
  labels.forEach((label, index) => {
    const option = document.createElement("option");
    option.value = String(index);
    option.textContent = label;
    selector.append(option);
  });
  selector.value = String(step);

  function selectStep(index) {
    step = Math.max(0, Math.min(history.challenges.length, index));
    selector.value = String(step);
    render();
  }

  function buildLegend() {
    legend.replaceChildren();
    history[view].forEach((series, index) => {
      const label = document.createElement("label");
      label.className = "chart-series";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = !hidden[view].has(series.id);
      checkbox.addEventListener("change", () => {
        if (checkbox.checked) hidden[view].delete(series.id);
        else hidden[view].add(series.id);
        render();
      });
      const swatch = document.createElement("span");
      swatch.className = `series-swatch series-color-${index % colors.length}`;
      swatch.setAttribute("aria-hidden", "true");
      const name = document.createElement("span");
      name.className = "series-name";
      name.textContent = series.name;
      const score = document.createElement("span");
      score.className = "series-score";
      score.dataset.series = String(series.id);
      label.append(checkbox, swatch, name, score);
      legend.append(label);
    });
  }

  function render() {
    const width = Math.max(240, plot.clientWidth);
    const height = 300;
    const margin = {left: 46, right: 16, top: 24, bottom: 48};
    const visible = history[view].filter(series => !hidden[view].has(series.id));
    let low = 0, high = 0;
    for (const series of visible) {
      for (const value of series.values) {
        low = Math.min(low, value);
        high = Math.max(high, value);
      }
    }
    const tickSize = Math.max(1, Math.ceil((high - low) / 4));
    low = Math.floor(low / tickSize) * tickSize;
    high = Math.ceil(high / tickSize) * tickSize;
    if (high === low) high = low + 4 * tickSize;
    const x = index => margin.left + index * (width - margin.left - margin.right) / history.challenges.length;
    const y = value => height - margin.bottom - (value - low) * (height - margin.top - margin.bottom) / (high - low);
    geometry = {width, margin, x};
    const svg = svgElement("svg", {viewBox: `0 0 ${width} ${height}`, role: "img",
      "aria-label": `Evolución de ${view === "people" ? "personas" : "equipos"}. Eje horizontal: pruebas. Eje vertical: puntos acumulados.`});
    svg.append(svgElement("title", {}, "Evolución cronológica de puntuaciones"));
    svg.append(svgElement("text", {x: margin.left, y: 14, class: "chart-label"}, "Puntos"));
    for (let value = low; value <= high; value += tickSize) {
      svg.append(svgElement("line", {x1: margin.left, x2: width - margin.right, y1: y(value), y2: y(value), class: value === 0 ? "chart-zero" : "chart-grid"}));
      svg.append(svgElement("text", {x: margin.left - 8, y: y(value) + 4, "text-anchor": "end", class: "chart-label"}, axisNumber.format(value)));
    }
    const tickEvery = Math.max(1, Math.ceil(history.challenges.length / Math.max(1, Math.floor((width - margin.left - margin.right) / 48))));
    for (let index = 0; index <= history.challenges.length; index++) {
      if (index !== 0 && index !== history.challenges.length && index % tickEvery !== 0) continue;
      const label = index === 0 ? "Inicio" : String(history.challenges[index - 1].chronology_position);
      svg.append(svgElement("text", {x: x(index), y: height - margin.bottom + 22, "text-anchor": "middle", class: "chart-label"}, label));
    }
    svg.append(svgElement("text", {x: width - margin.right, y: height - 4, "text-anchor": "end", class: "chart-label"}, "Pruebas (orden cronológico)"));
    svg.append(svgElement("line", {x1: x(step), x2: x(step), y1: margin.top, y2: height - margin.bottom, class: "chart-selected"}));
    history[view].forEach((series, index) => {
      if (hidden[view].has(series.id)) return;
      const color = colors[index % colors.length];
      svg.append(svgElement("polyline", {points: series.values.map((value, point) => `${x(point)},${y(value)}`).join(" "), fill: "none", stroke: color, "stroke-width": 2.5, "vector-effect": "non-scaling-stroke"}));
      const marker = svgElement("circle", {cx: x(step), cy: y(series.values[step]), r: 4, fill: color, stroke: "white", "stroke-width": 1});
      marker.append(svgElement("title", {}, `${series.name}: ${number.format(series.values[step])} pts · ${labels[step]}`));
      svg.append(marker);
    });
    plot.replaceChildren(svg);
    detail.textContent = step === 0 ? "Antes de la primera prueba: 0 puntos." : `Después de ${labels[step]}. Toca el gráfico o elige una prueba para consultar sus puntos.`;
    if (!visible.length) detail.textContent += " No hay series seleccionadas.";
    legend.querySelectorAll(".series-score").forEach(score => {
      const series = history[view].find(entry => entry.id === Number(score.dataset.series));
      score.textContent = `${number.format(series.values[step])} pts`;
    });
  }

  root.querySelectorAll("[data-view]").forEach(button => {
    button.addEventListener("click", () => {
      view = button.dataset.view;
      root.querySelectorAll("[data-view]").forEach(control => control.setAttribute("aria-pressed", String(control === button)));
      buildLegend();
      render();
    });
  });
  selector.addEventListener("change", () => selectStep(Number(selector.value)));
  plot.tabIndex = 0;
  plot.setAttribute("role", "group");
  plot.setAttribute("aria-label", "Gráfico interactivo. Usa las flechas izquierda y derecha para recorrer las pruebas.");
  plot.addEventListener("keydown", event => {
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      selectStep(step + (event.key === "ArrowRight" ? 1 : -1));
    }
  });
  plot.addEventListener("pointerdown", event => {
    if (!geometry) return;
    const box = plot.getBoundingClientRect();
    const position = (event.clientX - box.left) * geometry.width / box.width;
    selectStep(Math.round((position - geometry.margin.left) * history.challenges.length / (geometry.width - geometry.margin.left - geometry.margin.right)));
  });
  root.hidden = false;
  buildLegend();
  render();
  if (typeof ResizeObserver !== "undefined") new ResizeObserver(render).observe(plot);
  else window.addEventListener("resize", render);
})();
