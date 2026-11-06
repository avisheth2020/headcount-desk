// The one chart: approved headcount stepping down to usable open.
// Each bar is clickable and opens the rows behind it.
document.addEventListener("DOMContentLoaded", () => {
  const canvas = document.getElementById("waterfall");
  if (!canvas || !window.Chart) return;
  const steps = JSON.parse(canvas.dataset.steps);   // [{label, value, from, to, kind, href}]
  const css = getComputedStyle(document.documentElement);
  const color = { base: css.getPropertyValue("--bar-base").trim(), minus: css.getPropertyValue("--bar-minus").trim(), result: css.getPropertyValue("--accent").trim() };
  const ink = css.getPropertyValue("--text").trim(), muted = css.getPropertyValue("--muted").trim();
  const fmt = (n) => n.toLocaleString("en-US");
  const narrow = canvas.parentElement.clientWidth < 480;

  // Value labels above each bar, in text ink (not the bar color).
  const valueLabels = {
    id: "valueLabels",
    afterDatasetsDraw(chart) {
      const { ctx } = chart;
      ctx.save();
      ctx.font = `600 ${narrow ? 11 : 12}px Inter, system-ui, sans-serif`;
      ctx.fillStyle = ink;
      ctx.textAlign = narrow ? "left" : "center";
      chart.getDatasetMeta(0).data.forEach((bar, i) => {
        const s = steps[i], text = (s.kind === "minus" && s.value ? "−" : "") + fmt(s.value);
        if (narrow) ctx.fillText(text, Math.max(bar.x, bar.base) + 6, bar.y + 4);
        else ctx.fillText(text, bar.x, Math.min(bar.y, bar.base) - 6);
      });
      ctx.restore();
    },
  };

  new Chart(canvas, {
    type: "bar",
    data: {
      labels: steps.map((s) => s.label),
      datasets: [{
        data: steps.map((s) => [s.from, s.to]),
        backgroundColor: steps.map((s) => color[s.kind]),
        hoverBackgroundColor: steps.map((s) => color[s.kind]),
        borderRadius: 4, borderSkipped: false, maxBarThickness: narrow ? 22 : 56, minBarLength: 3,
      }],
    },
    options: {
      // On a phone the bars run sideways, so every label fits on one line.
      indexAxis: narrow ? "y" : "x",
      responsive: true, maintainAspectRatio: false, animation: { duration: 250 },
      layout: { padding: narrow ? { right: 48 } : { top: 22 } },
      // Hovering or tapping anywhere in a bar's lane counts, so the thin bars are easy to hit.
      interaction: { mode: "index", axis: narrow ? "y" : "x", intersect: false },
      onClick(_, hits) { if (hits.length) window.location.href = steps[hits[0].index].href; },
      onHover(e, hits) { e.native.target.style.cursor = hits.length ? "pointer" : "default"; },
      plugins: {
        legend: { display: false },
        tooltip: {
          displayColors: false, padding: 10,
          callbacks: {
            title: (items) => steps[items[0].dataIndex].label,
            label: (item) => {
              const s = steps[item.dataIndex];
              return [(s.kind === "minus" ? "−" : "") + fmt(s.value) + " positions", s.hint, "Click to see the rows"];
            },
          },
        },
      },
      scales: {
        [narrow ? "y" : "x"]: { grid: { display: false }, border: { color: "#e4e3df" }, ticks: { color: muted, font: { size: 12 }, maxRotation: 0, autoSkip: false } },
        [narrow ? "x" : "y"]: { beginAtZero: true, border: { display: false }, grid: { color: "#eeedea" }, ticks: { color: muted, maxTicksLimit: narrow ? 4 : 5, callback: (v) => fmt(v) } },
      },
    },
    plugins: [valueLabels],
  });
});
