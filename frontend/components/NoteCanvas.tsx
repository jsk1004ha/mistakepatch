"use client";

import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  type PointerEvent as ReactPointerEvent,
} from "react";

import type { HighlightShape } from "@/lib/types";

interface CanvasOverlay {
  id: string;
  x: number;
  y: number;
  w: number;
  h: number;
  shape: HighlightShape;
  selected: boolean;
}

interface NoteCanvasProps {
  brushColor: string;
  brushSize: number;
  eraserMode: boolean;
  overlays: CanvasOverlay[];
  annotationMode: boolean;
  onAnnotationTap: (point: { x: number; y: number }) => void;
}

export interface NoteCanvasHandle {
  exportAsFile: () => Promise<File | null>;
  clear: () => void;
  undo: () => boolean;
  redo: () => boolean;
}

interface StrokePoint {
  x: number;
  y: number;
  t: number;
  pressure: number;
  width: number;
}

interface StrokeRecord {
  id: string;
  color: string;
  baseSize: number;
  isPen: boolean;
  isEraser: boolean;
  points: StrokePoint[];
}

interface PointerSession {
  pointerId: number;
  stroke: StrokeRecord;
  isPen: boolean;
  lastPoint: StrokePoint;
}

interface DrawSegment {
  from: StrokePoint;
  to: StrokePoint;
  color: string;
  isEraser: boolean;
}

const MAX_POINTS_PER_STROKE = 600;
const MIN_POINT_DISTANCE = 0.2;
const CANVAS_BG_COLOR = "#fffdfb";

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function distance(a: { x: number; y: number }, b: { x: number; y: number }): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

function getNormalizedPoint(element: HTMLElement, clientX: number, clientY: number) {
  const rect = element.getBoundingClientRect();
  const x = (clientX - rect.left) / rect.width;
  const y = (clientY - rect.top) / rect.height;
  return {
    x: clamp(x, 0, 1),
    y: clamp(y, 0, 1),
  };
}

function createStrokeId() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `stroke_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
}

export const NoteCanvas = forwardRef<NoteCanvasHandle, NoteCanvasProps>(function NoteCanvas(
  { brushColor, brushSize, eraserMode, overlays, annotationMode, onAnnotationTap },
  ref,
) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const frameRef = useRef<HTMLDivElement | null>(null);
  const ratioRef = useRef(1);

  const strokesRef = useRef<StrokeRecord[]>([]);
  const redoStrokesRef = useRef<StrokeRecord[]>([]);
  const sessionRef = useRef<PointerSession | null>(null);
  const listenersAttachedRef = useRef(false);

  const drawQueueRef = useRef<DrawSegment[]>([]);
  const rafRef = useRef<number | null>(null);

  const brushColorRef = useRef(brushColor);
  const brushSizeRef = useRef(brushSize);
  const eraserModeRef = useRef(eraserMode);
  const annotationModeRef = useRef(annotationMode);

  const windowHandlersRef = useRef<{
    onMove: (event: PointerEvent) => void;
    onUp: (event: PointerEvent) => void;
  } | null>(null);

  useEffect(() => {
    brushColorRef.current = brushColor;
    brushSizeRef.current = brushSize;
    eraserModeRef.current = eraserMode;
    annotationModeRef.current = annotationMode;
  }, [annotationMode, brushColor, brushSize, eraserMode]);

  const getContext = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return null;
    return canvas.getContext("2d");
  }, []);

  const drawBackground = useCallback((ctx: CanvasRenderingContext2D, width: number, height: number) => {
    ctx.fillStyle = CANVAS_BG_COLOR;
    ctx.fillRect(0, 0, width, height);
  }, []);

  const toCanvasPoint = useCallback((clientX: number, clientY: number) => {
    const canvas = canvasRef.current;
    if (!canvas) return null;
    const rect = canvas.getBoundingClientRect();
    return {
      x: clamp(clientX - rect.left, 0, rect.width),
      y: clamp(clientY - rect.top, 0, rect.height),
    };
  }, []);

  const drawDot = useCallback(
    (ctx: CanvasRenderingContext2D, point: StrokePoint, color: string, isEraser = false) => {
      ctx.fillStyle = isEraser ? CANVAS_BG_COLOR : color;
      ctx.beginPath();
      ctx.arc(point.x, point.y, Math.max(point.width * 0.5, 0.8), 0, Math.PI * 2);
      ctx.fill();
    },
    [],
  );

  const drawSegment = useCallback((ctx: CanvasRenderingContext2D, segment: DrawSegment) => {
    const from = segment.from;
    const to = segment.to;
    const dx = to.x - from.x;
    const dy = to.y - from.y;
    const dist = Math.hypot(dx, dy);

    if (dist < 0.0001) {
      drawDot(ctx, to, segment.color, segment.isEraser);
      return;
    }

    const steps = Math.max(1, Math.ceil(dist / 1.2));
    ctx.fillStyle = segment.isEraser ? CANVAS_BG_COLOR : segment.color;

    for (let i = 0; i <= steps; i += 1) {
      const t = i / steps;
      const x = from.x + dx * t;
      const y = from.y + dy * t;
      const width = from.width + (to.width - from.width) * t;
      ctx.beginPath();
      ctx.arc(x, y, Math.max(width * 0.5, 0.8), 0, Math.PI * 2);
      ctx.fill();
    }
  }, [drawDot]);

  const flushQueue = useCallback(() => {
    rafRef.current = null;
    const ctx = getContext();
    if (!ctx) {
      drawQueueRef.current.length = 0;
      return;
    }

    const queue = drawQueueRef.current.splice(0, drawQueueRef.current.length);
    for (const segment of queue) {
      drawSegment(ctx, segment);
    }
  }, [drawSegment, getContext]);

  const scheduleFlush = useCallback(() => {
    if (rafRef.current !== null) return;
    rafRef.current = window.requestAnimationFrame(flushQueue);
  }, [flushQueue]);

  const redrawFromModel = useCallback(() => {
    const canvas = canvasRef.current;
    const ctx = getContext();
    if (!canvas || !ctx) return;

    const cssWidth = canvas.width / ratioRef.current;
    const cssHeight = canvas.height / ratioRef.current;
    drawBackground(ctx, cssWidth, cssHeight);

    for (const stroke of strokesRef.current) {
      const points = stroke.points;
      if (points.length === 0) continue;
      drawDot(ctx, points[0], stroke.color, stroke.isEraser);
      for (let i = 1; i < points.length; i += 1) {
        drawSegment(ctx, {
          from: points[i - 1],
          to: points[i],
          color: stroke.color,
          isEraser: stroke.isEraser,
        });
      }
    }
  }, [drawBackground, drawDot, drawSegment, getContext]);

  const resizeCanvas = useCallback(() => {
    const canvas = canvasRef.current;
    const frame = frameRef.current;
    if (!canvas || !frame) return;

    const rect = frame.getBoundingClientRect();
    const ratio = window.devicePixelRatio || 1;
    const nextWidth = Math.max(1, Math.floor(rect.width * ratio));
    const nextHeight = Math.max(1, Math.floor(rect.height * ratio));
    if (canvas.width === nextWidth && canvas.height === nextHeight) return;

    canvas.width = nextWidth;
    canvas.height = nextHeight;

    ratioRef.current = ratio;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);

    redrawFromModel();
  }, [redrawFromModel]);

  const detachWindowListeners = useCallback(() => {
    if (!listenersAttachedRef.current) return;
    const handlers = windowHandlersRef.current;
    if (!handlers) return;
    window.removeEventListener("pointermove", handlers.onMove);
    window.removeEventListener("pointerup", handlers.onUp);
    window.removeEventListener("pointercancel", handlers.onUp);
    listenersAttachedRef.current = false;
  }, []);

  const stopSession = useCallback(
    (pointerId: number | null = null) => {
      const session = sessionRef.current;
      if (!session) return;
      if (pointerId !== null && session.pointerId !== pointerId) return;

      const canvas = canvasRef.current;
      if (canvas && canvas.hasPointerCapture(session.pointerId)) {
        try {
          canvas.releasePointerCapture(session.pointerId);
        } catch {
          // ignore release failures
        }
      }
      sessionRef.current = null;
      detachWindowListeners();
    },
    [detachWindowListeners],
  );

  const calcPointWidth = useCallback(
    (isPen: boolean, pressure: number, previous: StrokePoint | null, nextX: number, nextY: number, nextT: number) => {
      const base = brushSizeRef.current;
      if (isPen) {
        return clamp(base * (0.28 + pressure * 1.12), base * 0.25, base * 1.5);
      }
      if (!previous) return base;

      const dt = Math.max(1, nextT - previous.t);
      const v = distance(previous, { x: nextX, y: nextY }) / dt;
      const factor = clamp(1.08 - v * 0.5, 0.38, 1);
      return base * factor;
    },
    [],
  );

  const appendPointToStroke = useCallback(
    (session: PointerSession, point: StrokePoint) => {
      const prev = session.lastPoint;
      if (distance(prev, point) < MIN_POINT_DISTANCE) return;

      session.stroke.points.push(point);
      drawQueueRef.current.push({
        from: prev,
        to: point,
        color: session.stroke.color,
        isEraser: session.stroke.isEraser,
      });
      scheduleFlush();
      session.lastPoint = point;

      // Similar to draw-shape strategies, split very long strokes for stability.
      if (session.stroke.points.length >= MAX_POINTS_PER_STROKE) {
        const splitStart = session.lastPoint;
        const nextStroke: StrokeRecord = {
          id: createStrokeId(),
          color: session.stroke.color,
          baseSize: session.stroke.baseSize,
          isPen: session.stroke.isPen,
          isEraser: session.stroke.isEraser,
          points: [splitStart],
        };
        strokesRef.current.push(nextStroke);
        session.stroke = nextStroke;
      }
    },
    [scheduleFlush],
  );

  const ensureWindowHandlers = useCallback(() => {
    if (windowHandlersRef.current) return windowHandlersRef.current;

    const onMove = (event: PointerEvent) => {
      const session = sessionRef.current;
      if (!session) return;
      if (event.pointerId !== session.pointerId) return;
      if (annotationModeRef.current) return;
      event.preventDefault();

      const rawEvents =
        typeof event.getCoalescedEvents === "function" ? event.getCoalescedEvents() : [event];

      for (const raw of rawEvents) {
        const pos = toCanvasPoint(raw.clientX, raw.clientY);
        if (!pos) continue;
        const pressure = clamp(raw.pressure || (session.isPen ? 0.5 : 0.5), 0.05, 1);
        const width = calcPointWidth(
          session.isPen,
          pressure,
          session.lastPoint,
          pos.x,
          pos.y,
          raw.timeStamp,
        );
        const nextPoint: StrokePoint = {
          x: pos.x,
          y: pos.y,
          t: raw.timeStamp,
          pressure,
          width,
        };
        appendPointToStroke(session, nextPoint);
      }
    };

    const onUp = (event: PointerEvent) => {
      stopSession(event.pointerId);
    };

    windowHandlersRef.current = { onMove, onUp };
    return windowHandlersRef.current;
  }, [appendPointToStroke, calcPointWidth, stopSession, toCanvasPoint]);

  const attachWindowListeners = useCallback(() => {
    if (listenersAttachedRef.current) return;
    const handlers = ensureWindowHandlers();
    window.addEventListener("pointermove", handlers.onMove, { passive: false });
    window.addEventListener("pointerup", handlers.onUp, { passive: false });
    window.addEventListener("pointercancel", handlers.onUp, { passive: false });
    listenersAttachedRef.current = true;
  }, [ensureWindowHandlers]);

  useEffect(() => {
    resizeCanvas();
    const observer = new ResizeObserver(() => resizeCanvas());
    const drawQueue = drawQueueRef.current;
    if (frameRef.current) {
      observer.observe(frameRef.current);
    }
    return () => {
      observer.disconnect();
      stopSession();
      if (rafRef.current !== null) {
        window.cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
      drawQueue.length = 0;
    };
  }, [resizeCanvas, stopSession]);

  useEffect(() => {
    if (annotationMode) {
      stopSession();
    }
  }, [annotationMode, stopSession]);

  const handlePointerDown = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    event.preventDefault();

    if (annotationModeRef.current) {
      const point = getNormalizedPoint(event.currentTarget, event.clientX, event.clientY);
      onAnnotationTap(point);
      return;
    }

    if (event.pointerType === "mouse" && event.button !== 0) return;
    if (sessionRef.current) return;

    const pos = toCanvasPoint(event.clientX, event.clientY);
    if (!pos) return;

    const isPen = event.pointerType === "pen";
    const pressure = clamp(event.pressure || (isPen ? 0.5 : 0.5), 0.05, 1);
    const firstWidth = calcPointWidth(isPen, pressure, null, pos.x, pos.y, event.timeStamp);
    const firstPoint: StrokePoint = {
      x: pos.x,
      y: pos.y,
      t: event.timeStamp,
      pressure,
      width: firstWidth,
    };

    const stroke: StrokeRecord = {
      id: createStrokeId(),
      color: brushColorRef.current,
      baseSize: brushSizeRef.current,
      isPen,
      isEraser: eraserModeRef.current,
      points: [firstPoint],
    };
    strokesRef.current.push(stroke);
    redoStrokesRef.current = [];

    const ctx = getContext();
    if (ctx) {
      drawDot(ctx, firstPoint, stroke.color, stroke.isEraser);
    }

    sessionRef.current = {
      pointerId: event.pointerId,
      stroke,
      isPen,
      lastPoint: firstPoint,
    };

    try {
      event.currentTarget.setPointerCapture(event.pointerId);
    } catch {
      // ignore capture failures in unsupported environments
    }
    attachWindowListeners();
  };

  useImperativeHandle(ref, () => ({
    exportAsFile: async () => {
      const canvas = canvasRef.current;
      if (!canvas) return null;
      const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png", 1));
      if (!blob) return null;
      return new File([blob], "note-solution.png", { type: "image/png" });
    },
    clear: () => {
      stopSession();
      strokesRef.current = [];
      redoStrokesRef.current = [];
      drawQueueRef.current.length = 0;
      if (rafRef.current !== null) {
        window.cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
      redrawFromModel();
    },
    undo: () => {
      stopSession();
      if (strokesRef.current.length === 0) return false;
      drawQueueRef.current.length = 0;
      if (rafRef.current !== null) {
        window.cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
      const removed = strokesRef.current.pop();
      if (!removed) return false;
      redoStrokesRef.current.push(removed);
      redrawFromModel();
      return true;
    },
    redo: () => {
      stopSession();
      if (redoStrokesRef.current.length === 0) return false;
      drawQueueRef.current.length = 0;
      if (rafRef.current !== null) {
        window.cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
      const restored = redoStrokesRef.current.pop();
      if (!restored) return false;
      strokesRef.current.push(restored);
      redrawFromModel();
      return true;
    },
  }));

  return (
    <section className="noteCanvasFrame" ref={frameRef}>
      <canvas
        ref={canvasRef}
        className={`noteCanvas ${annotationMode ? "annotationMode" : ""} ${eraserMode ? "eraserMode" : ""}`}
        onPointerDown={handlePointerDown}
      />
      {overlays.map((overlay) => (
        <span
          key={overlay.id}
          className={`noteOverlay ${overlay.shape} ${overlay.selected ? "selected" : ""}`}
          style={{
            left: `${overlay.x * 100}%`,
            top: `${overlay.y * 100}%`,
            width: `${overlay.w * 100}%`,
            height: `${overlay.h * 100}%`,
          }}
        />
      ))}
      {annotationMode && (
        <div className="annotationHint">선택된 감점 포인트 위치를 필기 화면에서 한 번 탭하세요.</div>
      )}
    </section>
  );
});

