/* Hand-drawn canvas charts — no framework. */
(function (global) {
  function css(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }
  function drawLine(canvas, points, opts) {
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const w = canvas.width, h = canvas.height;
    ctx.clearRect(0, 0, w, h);
    const vals = (points || []).map((p) => p.y).filter((v) => typeof v === "number");
    if (vals.length < 2) return false;
    const min = Math.min(...vals), max = Math.max(...vals);
    const pad = (max - min) * 0.12 || Math.abs(min) * 0.02 || 1;
    const lo = min - pad, hi = max + pad;
    const x0 = 8, x1 = w - 8, y0 = 12, y1 = h - 12;
    function X(i) { return x0 + (i / (points.length - 1)) * (x1 - x0); }
    function Y(v) { return y1 - ((v - lo) / (hi - lo)) * (y1 - y0); }
    const up = vals[vals.length - 1] >= vals[0];
    ctx.strokeStyle = up ? css("--green") || "#00D395" : css("--red") || "#FF453A";
    ctx.lineWidth = 2;
    ctx.beginPath();
    points.forEach((p, i) => {
      const y = Y(p.y);
      if (i === 0) ctx.moveTo(X(i), y);
      else ctx.lineTo(X(i), y);
    });
    ctx.stroke();
    const fill = ctx.createLinearGradient(0, y0, 0, y1);
    fill.addColorStop(0, up ? "rgba(0,211,149,0.22)" : "rgba(255,69,58,0.22)");
    fill.addColorStop(1, "rgba(0,0,0,0)");
    ctx.lineTo(X(points.length - 1), y1);
    ctx.lineTo(X(0), y1);
    ctx.closePath();
    ctx.fillStyle = fill;
    ctx.fill();
    if (opts && opts.dash != null) {
      ctx.setLineDash([6, 6]);
      ctx.strokeStyle = css("--orange") || "#FF9F0A";
      ctx.beginPath();
      ctx.moveTo(x0, Y(opts.dash));
      ctx.lineTo(x1, Y(opts.dash));
      ctx.stroke();
      ctx.setLineDash([]);
    }
    return true;
  }
  function drawCandles(canvas, points, opts) {
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const w = canvas.width, h = canvas.height;
    ctx.clearRect(0, 0, w, h);
    if (!points || points.length < 2) return false;
    // bucket into candles
    const buckets = Math.min(40, points.length);
    const size = Math.max(1, Math.floor(points.length / buckets));
    const candles = [];
    for (let i = 0; i < points.length; i += size) {
      const slice = points.slice(i, i + size).map((p) => p.y);
      if (!slice.length) continue;
      candles.push({ o: slice[0], h: Math.max(...slice), l: Math.min(...slice), c: slice[slice.length - 1] });
    }
    const nums = candles.flatMap((c) => [c.h, c.l]);
    if (opts && opts.dash != null) nums.push(opts.dash);
    const min = Math.min(...nums), max = Math.max(...nums);
    const pad = (max - min) * 0.12 || 1;
    const lo = min - pad, hi = max + pad;
    const x0 = 10, x1 = w - 10, y0 = 14, y1 = h - 14;
    function Y(v) { return y1 - ((v - lo) / (hi - lo)) * (y1 - y0); }
    const slot = (x1 - x0) / candles.length;
    candles.forEach((c, i) => {
      const x = x0 + i * slot + slot / 2;
      const up = c.c >= c.o;
      ctx.strokeStyle = up ? "#00D395" : "#FF453A";
      ctx.fillStyle = ctx.strokeStyle;
      ctx.beginPath();
      ctx.moveTo(x, Y(c.h));
      ctx.lineTo(x, Y(c.l));
      ctx.stroke();
      const top = Y(Math.max(c.o, c.c));
      const bot = Y(Math.min(c.o, c.c));
      ctx.fillRect(x - Math.max(2, slot * 0.28), top, Math.max(4, slot * 0.56), Math.max(1, bot - top));
    });
    if (opts && opts.dash != null) {
      ctx.setLineDash([5, 5]);
      ctx.strokeStyle = css("--orange") || "#FF9F0A";
      ctx.beginPath();
      ctx.moveTo(x0, Y(opts.dash));
      ctx.lineTo(x1, Y(opts.dash));
      ctx.stroke();
      ctx.setLineDash([]);
    }
    return true;
  }
  global.DeskChart = { drawLine, drawCandles };
})(window);
