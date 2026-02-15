import { useEffect, useMemo, useRef, useState } from "react";
import { AnnotationBracket, AnnotationCallout } from "react-annotation";

const RED = "#D32F2F";
const STYLES = {
  fontFamily: "'Kalam', 'Caveat', 'Patrick Hand', 'Comic Sans MS', 'Bradley Hand', cursive",
  fontSize: 14,
  color: RED
};

const hashText = (text) => {
  let hash = 0;
  const str = String(text || "");
  for (let i = 0; i < str.length; i += 1) {
    hash = (hash << 5) - hash + str.charCodeAt(i);
    hash |= 0;
  }
  return hash;
};

const drawWavyLine = (x, y, width, seed = 0) => {
  const baseY = y + 12;
  const step = 5;
  const steps = Math.max(6, Math.floor(width / step));
  let path = `M ${x} ${baseY}`;
  for (let i = 1; i <= steps; i += 1) {
    const dx = i * step;
    const noise = ((seed + i) % 3) * 0.6;
    const dy = Math.sin(i) * 3 + noise;
    path += ` L ${x + dx} ${baseY + dy}`;
  }
  return path;
};

const drawCircleAndConnect = (box, marginX) => {
  const cx = box.x1 + (box.x2 - box.x1) / 2;
  const cy = box.y1 + (box.y2 - box.y1) / 2;
  const rx = (box.x2 - box.x1) / 2 + 5;
  const ry = (box.y2 - box.y1) / 2 + 5;
  const circlePath = `
    M ${cx - rx} ${cy}
    Q ${cx - rx} ${cy - ry} ${cx} ${cy - ry}
    Q ${cx + rx} ${cy - ry} ${cx + rx} ${cy}
    Q ${cx + rx} ${cy + ry} ${cx} ${cy + ry}
    Q ${cx - rx} ${cy + ry} ${cx - rx} ${cy}
  `;
  const linePath = `M ${cx + rx} ${cy} L ${marginX - 10} ${cy}`;
  return { circlePath, linePath, cx, cy };
};

const wrapText = (text, maxChars) => {
  const words = String(text || "").split(/\s+/).filter(Boolean);
  const lines = [];
  let current = "";
  words.forEach((word) => {
    const next = current ? `${current} ${word}` : word;
    if (next.length > maxChars) {
      if (current) lines.push(current);
      current = word;
    } else {
      current = next;
    }
  });
  if (current) lines.push(current);
  return lines;
};

const clamp = (value, min, max) => Math.max(min, Math.min(max, value));

const resolveBox = (ann, width, height) => {
  if (ann?.x_percent !== undefined && ann?.y_percent !== undefined) {
    const x1 = ann.x_percent * width;
    const y1 = ann.y_percent * height;
    const w = (ann.w_percent ?? 0) * width;
    const h = (ann.h_percent ?? 0) * height;
    return { x1, y1, x2: x1 + Math.max(2, w), y2: y1 + Math.max(2, h) };
  }
  if (ann?.box_2d && ann.box_2d.length === 4) {
    const [ymin, xmin, ymax, xmax] = ann.box_2d;
    const x1 = (xmin / 1000) * width;
    const y1 = (ymin / 1000) * height;
    const x2 = (xmax / 1000) * width;
    const y2 = (ymax / 1000) * height;
    return { x1, y1, x2, y2 };
  }
  if (ann?.x !== undefined && ann?.y !== undefined) {
    const size = ann?.size || 20;
    return { x1: ann.x, y1: ann.y, x2: ann.x + size, y2: ann.y + size };
  }
  return null;
};

export default function HandwrittenOverlay({
  annotations,
  width,
  height,
  show
}) {
  const containerRef = useRef(null);
  const [scale, setScale] = useState(1);

  useEffect(() => {
    const updateScale = () => {
      if (!containerRef.current || !width) return;
      const rect = containerRef.current.getBoundingClientRect();
      setScale(rect.width / width);
    };
    updateScale();
    window.addEventListener("resize", updateScale);
    return () => window.removeEventListener("resize", updateScale);
  }, [width]);

  // Limit to max 6 annotations and filter out top 25%
  const normalized = useMemo(() => {
    const filtered = (annotations || []).filter((ann) => {
      const anchorY = ann.anchor_y ?? ann.anchorY ?? ann.y_percent ?? ann.y ?? null;
      if (anchorY !== null) {
        const normY = typeof anchorY === "number" ? anchorY : 0;
        if (normY < 0.25) return false;
      }
      if (ann.y_start !== undefined || ann.y_start_percent !== undefined) {
        const yStart = ann.y_start ?? ann.y_start_percent ?? 0;
        if (yStart < 0.25) return false;
      }
      return true;
    });
    return filtered.slice(0, 6);
  }, [annotations]);

  const headerSafeY = Math.max(150, height * 0.25);
  const feedbackAnnotations = useMemo(() => {
    const items = normalized
      .map((ann, idx) => {
        const type = String(ann?.type || "").toUpperCase();
        if (type !== "FEEDBACK" && type !== "FEEDBACK_UNDERLINE" && type !== "BOX_COMMENT") {
          return null;
        }
        const rawBox = resolveBox(ann, width, height);
        if (!rawBox) return null;
        const boxHeight = rawBox.y2 - rawBox.y1;
        if (rawBox.y2 < headerSafeY || boxHeight < 20) return null;
        const label = String(ann.label || ann.short_label || ann.text || "").trim();
        return { idx, ann, box: rawBox, label };
      })
      .filter(Boolean)
      .sort((a, b) => a.box.y1 - b.box.y1);
    return items;
  }, [normalized, width, height, headerSafeY]);

  const feedbackLayout = useMemo(() => {
    if (!feedbackAnnotations.length) return [];
    let lastBottom = headerSafeY * scale;
    const boxHeight = 80;
    return feedbackAnnotations.map((item) => {
      const x = item.box.x1 * scale;
      const y = item.box.y1 * scale;
      const w = (item.box.x2 - item.box.x1) * scale;
      const h = (item.box.y2 - item.box.y1) * scale;
      let renderY = y;
      if (renderY < lastBottom + 20) {
        renderY = lastBottom + 20;
      }
      lastBottom = renderY + boxHeight;
      return { ...item, x, y, w, h, renderY };
    });
  }, [feedbackAnnotations, headerSafeY, scale]);

  const layoutByIndex = useMemo(() => {
    const map = {};
    feedbackLayout.forEach((item) => {
      map[item.idx] = item;
    });
    return map;
  }, [feedbackLayout]);

  if (!show || !width || !height || normalized.length === 0) {
    return null;
  }

  const roughFilter = (
    <svg style={{ width: 0, height: 0, position: "absolute" }}>
      <filter id="roughpaper">
        <feTurbulence type="fractalNoise" baseFrequency="0.02" numOctaves="3" result="noise" />
        <feDisplacementMap in="SourceGraphic" in2="noise" scale="2" />
      </filter>
    </svg>
  );

  return (
    <div ref={containerRef} className="absolute inset-0 pointer-events-none">
      {roughFilter}
      <svg width="100%" height="100%" style={{ filter: "url(#roughpaper)" }}>
        {normalized.map((ann, i) => {
          const type = String(ann?.type || "").toUpperCase();
          const rawBox = resolveBox(ann, width, height);
          const box = rawBox
            ? {
                x1: rawBox.x1 * scale,
                y1: rawBox.y1 * scale,
                x2: rawBox.x2 * scale,
                y2: rawBox.y2 * scale
              }
            : null;

          if (type === "MARGIN_LEASH") {
            const anchorX = ann.anchor_x ?? ann.anchorX ?? ann.anchor_x_percent ?? ann.anchor_x;
            const anchorY = ann.anchor_y ?? ann.anchorY ?? ann.anchor_y_percent ?? ann.anchor_y;
            const anchorXpx = anchorX !== undefined ? anchorX * width * scale : box?.x2 ?? 0;
            const anchorYpx = anchorY !== undefined ? anchorY * height * scale : box ? (box.y1 + box.y2) / 2 : 0;
            const maxDx = Math.min(140, width * scale * 0.18);
            const dx = anchorXpx > width * 0.7 ? -maxDx : maxDx;
            const dy = -10;
            const title = String(ann.label || ann.short_label || ann.text || "").trim();
            const feedback = String(ann.feedback || "").trim();

            return (
              <AnnotationCallout
                key={`leash-${i}`}
                x={anchorXpx}
                y={anchorYpx}
                dx={dx}
                dy={dy}
                color={STYLES.color}
                note={{
                  title,
                  label: feedback || undefined,
                  wrap: 140,
                  align: "middle",
                  orientation: "leftRight"
                }}
                connector={{ type: "line" }}
                className="handwritten"
              />
            );
          }

          if (type === "TICK") {
            if (!box) return null;
            const x = box.x2 + 6;
            const y = box.y2 - 6;
            return (
              <path
                key={`tick-${i}`}
                d={`M ${x} ${y} L ${x + 6} ${y + 6} L ${x + 18} ${y - 10}`}
                fill="none"
                stroke={STYLES.color}
                strokeWidth="2"
                className="handwritten"
              />
            );
          }

          if (type === "CROSS") {
            if (!box) return null;
            const x = box.x2 + 6;
            const y = box.y1 + 2;
            return (
              <g key={`cross-${i}`} className="handwritten">
                <line x1={x} y1={y} x2={x + 12} y2={y + 12} stroke={STYLES.color} strokeWidth="2" />
                <line x1={x + 12} y1={y} x2={x} y2={y + 12} stroke={STYLES.color} strokeWidth="2" />
              </g>
            );
          }

          if (type === "MARGIN_NOTE") {
            if (!box) return null;
            const marginX = width * scale * 0.92;
            const label = String(ann.label || ann.short_label || ann.text || "").trim();
            const feedback = String(ann.feedback || "").trim();
            const { circlePath, linePath, cy } = drawCircleAndConnect(box, marginX);
            const textX = marginX + 2;
            const textY = cy - 4;
            const lines = wrapText(label, 14);
            const lineHeight = 16;
            return (
              <g key={`note-${i}`} className="handwritten">
                <path d={circlePath} fill="none" stroke={STYLES.color} strokeWidth="2" />
                <path d={linePath} fill="none" stroke={STYLES.color} strokeWidth="2" />
                <text
                  x={textX}
                  y={textY}
                  transform={`rotate(-2 ${textX} ${textY})`}
                  style={{ fontFamily: STYLES.fontFamily, fontSize: STYLES.fontSize, fill: STYLES.color }}
                >
                  {lines.map((line, idx) => (
                    <tspan key={idx} x={textX} dy={idx === 0 ? 0 : lineHeight}>
                      {line}
                    </tspan>
                  ))}
                  {feedback ? <title>{feedback}</title> : null}
                </text>
              </g>
            );
          }

          if (type === "FEEDBACK_UNDERLINE" || type === "FEEDBACK" || type === "BOX_COMMENT") {
            if (!box) return null;
            const layout = layoutByIndex[i];
            if (!layout) return null;
            const containerWidth = containerRef.current?.clientWidth || width * scale;
            const boxLeft = containerWidth - 160;
            const connectorY = layout.renderY + 24;

            return (
              <g key={`feedback-${i}`} className="handwritten">
                <path
                  d={`M ${layout.x} ${layout.y + layout.h} Q ${layout.x + layout.w / 2} ${layout.y + layout.h + 5} ${layout.x + layout.w} ${layout.y + layout.h}`}
                  fill="none"
                  stroke={STYLES.color}
                  strokeWidth="2"
                />
                <path
                  d={`M ${layout.x + layout.w} ${layout.y + layout.h} C ${layout.x + layout.w + 50} ${layout.y + layout.h} ${boxLeft - 50} ${connectorY} ${boxLeft} ${connectorY}`}
                  fill="none"
                  stroke={STYLES.color}
                  strokeWidth="1.5"
                  strokeDasharray="5,3"
                />
              </g>
            );
          }

          if (type === "EMPHASIS_UNDERLINE") {
            if (!box) return null;
            const widthPx = Math.max(10, box.x2 - box.x1);
            const seed = hashText(ann.anchor_text || ann.label || ann.text || "");
            const path = drawWavyLine(box.x1, box.y2, widthPx, seed);
            return (
              <path
                key={`wave-${i}`}
                d={path}
                fill="none"
                stroke={STYLES.color}
                strokeWidth="2"
                className="handwritten"
              />
            );
          }

          if (type === "GROUP_BRACKET") {
            const yStart = (ann.y_start ?? ann.y_start_percent ?? 0.3) * height;
            const yEnd = (ann.y_end ?? ann.y_end_percent ?? 0.45) * height;
            const bracketX = 50;
            const heightPx = Math.max(10, yEnd - yStart);
            const title = String(ann.label || ann.short_label || ann.text || "").trim();

            return (
              <AnnotationBracket
                key={`bracket-${i}`}
                x={bracketX}
                y={yStart}
                height={heightPx}
                dy={0}
                dx={-20}
                color={STYLES.color}
                note={{
                  title,
                  align: "right",
                  orientation: "leftRight"
                }}
                className="handwritten"
              />
            );
          }

          if (type === "INLINE_TICK" || type === "CHECKMARK" || type === "TICK") {
            const x = box ? box.x2 + 6 : 0;
            const y = box ? box.y1 + 10 : 0;
            const size = 14;
            return (
              <path
                key={`tick-${i}`}
                d={`M ${x} ${y} L ${x + size * 0.35} ${y + size * 0.5} L ${x + size} ${y - size * 0.2}`}
                fill="none"
                stroke="#2e7d32"
                strokeWidth="2"
                className="handwritten"
              />
            );
          }

          if (type === "DOUBLE_TICK") {
            const x = box ? box.x2 + 6 : 0;
            const y = box ? box.y1 + 10 : 0;
            const size = 14;
            return (
              <g key={`dtick-${i}`} className="handwritten">
                <path
                  d={`M ${x} ${y} L ${x + size * 0.35} ${y + size * 0.5} L ${x + size} ${y - size * 0.2}`}
                  fill="none"
                  stroke="#2e7d32"
                  strokeWidth="2"
                />
                <path
                  d={`M ${x + 6} ${y + 4} L ${x + 6 + size * 0.35} ${y + 4 + size * 0.5} L ${x + 6 + size} ${y + 4 - size * 0.2}`}
                  fill="none"
                  stroke="#2e7d32"
                  strokeWidth="2"
                />
              </g>
            );
          }

          return null;
        })}
      </svg>

      {feedbackLayout.length > 0 && (
        <div
          style={{
            position: "absolute",
            right: "10px",
            top: 0,
            bottom: 0,
            width: "140px",
            pointerEvents: "none"
          }}
        >
          {feedbackLayout.map((item) => (
            <div
              key={`fb-card-${item.idx}`}
              style={{
                position: "absolute",
                top: `${item.renderY}px`,
                right: 0,
                width: "140px",
                background: "rgba(255, 255, 255, 0.95)",
                border: `2px solid ${STYLES.color}`,
                borderRadius: "255px 15px 225px 15px/15px 225px 15px 255px",
                padding: "10px",
                fontFamily: STYLES.fontFamily,
                fontSize: "13px",
                color: STYLES.color,
                lineHeight: "1.3",
                boxShadow: "3px 3px 0 rgba(211,47,47,0.2)",
                wordWrap: "break-word"
              }}
            >
              {item.label}
            </div>
          ))}
        </div>
      )}

      <style>{`
        .handwritten text {
          font-family: ${STYLES.fontFamily};
          font-weight: 700;
          fill: ${STYLES.color} !important;
        }
        .handwritten path {
          stroke: ${STYLES.color} !important;
          stroke-width: 2px;
        }
      `}</style>
    </div>
  );
}
