import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  Radio,
  Trash2,
  Flame,
  CheckCircle2,
  Zap,
  PlayCircle,
  Activity,
  Layers,
  FileVideo,
  AlertTriangle,
  Square,
  ChevronDown,
  Volume2,
  VolumeX,
  ShieldAlert,
  ShieldCheck,
  History,
  AlertCircle
} from 'lucide-react';
import { civicsenseApi } from '../services/api';
import { toast } from 'sonner';

export default function Landing() {
  // Engine telemetry & state
  const [engineState, setEngineState] = useState({
    running: false,
    status: 'STANDBY',
    source: '0',
    fps: 0,
    frame_idx: 0,
    primary_hazard: null,
    pothole: {
      detected: false,
      count: 0,
      confidence: 0,
      status: 'STANDBY',
      bboxes: [],
    },
    fire_smoke: {
      detected: false,
      fire_detected: false,
      smoke_detected: false,
      confidence: 0,
      status: 'STANDBY',
      bboxes: [],
    },
    overflow: {
      detected: false,
      status: 'STANDBY',
      confidence: 0,
      label: 'Engine Standby',
    },
    esp32: {
      enabled: true,
      ip: '192.168.206.33',
      last_msg: 'Idle',
      active_signal: 'normal',
    },
    total_incidents: 0,
    recent_incidents: [],
  });

  const [isLoadingAction, setIsLoadingAction] = useState(false);
  const [simulateMenuOpen, setSimulateMenuOpen] = useState(false);
  const [soundEnabled, setSoundEnabled] = useState(false);
  const pollTimerRef = useRef(null);
  const lastSoundPlayedRef = useRef(0);

  // Play synthesized web audio alert beep when hazard active
  const triggerAudioChime = useCallback((hazardType) => {
    if (!soundEnabled) return;
    const now = Date.now();
    if (now - lastSoundPlayedRef.current < 2000) return; // Debounce 2s
    lastSoundPlayedRef.current = now;

    try {
      const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();
      osc.connect(gain);
      gain.connect(audioCtx.destination);

      if (hazardType === 'fire') {
        osc.type = 'sawtooth';
        osc.frequency.setValueAtTime(880, audioCtx.currentTime);
        osc.frequency.exponentialRampToValueAtTime(440, audioCtx.currentTime + 0.35);
      } else if (hazardType === 'pothole') {
        osc.type = 'triangle';
        osc.frequency.setValueAtTime(400, audioCtx.currentTime);
        osc.frequency.exponentialRampToValueAtTime(700, audioCtx.currentTime + 0.25);
      } else {
        osc.type = 'sine';
        osc.frequency.setValueAtTime(520, audioCtx.currentTime);
        osc.frequency.exponentialRampToValueAtTime(660, audioCtx.currentTime + 0.3);
      }

      gain.gain.setValueAtTime(0.2, audioCtx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 0.35);
      osc.start();
      osc.stop(audioCtx.currentTime + 0.35);
    } catch {
      // AudioContext not allowed or not supported
    }
  }, [soundEnabled]);

  // Fetch telemetry status from backend API
  const fetchStatus = useCallback(async () => {
    try {
      const res = await civicsenseApi.getStatus();
      if (res.data) {
        setEngineState((prev) => ({
          ...prev,
          ...res.data,
        }));
        if (res.data.primary_hazard) {
          triggerAudioChime(res.data.primary_hazard);
        }
      }
    } catch {
      // Backend temporarily unreachable; preserve existing telemetry
    }
  }, [triggerAudioChime]);

  // Poll loop: Faster when running (700ms), slower when standby (2000ms)
  useEffect(() => {
    fetchStatus();

    const interval = engineState.running ? 700 : 2000;
    pollTimerRef.current = setInterval(fetchStatus, interval);

    return () => {
      if (pollTimerRef.current) clearInterval(pollTimerRef.current);
    };
  }, [engineState.running, fetchStatus]);

  // Start engine handler
  const handleStartEngine = async (sourceType) => {
    setIsLoadingAction(true);
    const sourceParam = sourceType === 'webcam' ? '0' : 'Watch Video_ Terrible potholes in Rangoon Road.mp4';
    try {
      toast.info(`Launching CivicSense Engine (${sourceType === 'webcam' ? 'Webcam 0' : 'Road Video'})...`);
      const res = await civicsenseApi.startLive({
        source: sourceParam,
        esp_ip: '192.168.206.33',
        enable_esp: true,
      });
      if (res.data.status === 'RUNNING' || res.data.status === 'ALREADY_RUNNING') {
        toast.success(`CivicSense Unified AI Engine active!`);
        fetchStatus();
      }
    } catch (err) {
      const msg = err.response?.data?.detail || err.message || 'Failed to start AI engine';
      toast.error(`Start error: ${msg}`);
    } finally {
      setIsLoadingAction(false);
    }
  };

  // Stop engine handler
  const handleStopEngine = async () => {
    setIsLoadingAction(true);
    try {
      await civicsenseApi.stopLive();
      toast.success('CivicSense Engine stopped cleanly.');
      fetchStatus();
    } catch {
      toast.error('Failed to stop engine');
    } finally {
      setIsLoadingAction(false);
    }
  };

  // Trigger simulation for testing live model cards
  const handleSimulate = async (type) => {
    setSimulateMenuOpen(false);
    try {
      const res = await civicsenseApi.simulate({ hazard_type: type });
      if (res.data) {
        setEngineState(res.data);
        toast.success(`Simulated ${type.toUpperCase()} event active!`);
        return;
      }
    } catch {
      // Local fallback simulation if backend is offline or starting
      const isPothole = type === 'pothole' || type === 'all';
      const isFire = type === 'fire' || type === 'all';
      const isOverflow = type === 'overflow' || type === 'all';
      const isNormal = type === 'normal';

      const simulatedState = {
        running: !isNormal,
        status: isNormal ? 'STANDBY' : 'RUNNING',
        source: 'Simulated Stream',
        fps: isNormal ? 0 : 25.0,
        frame_idx: Math.floor(Math.random() * 850) + 140,
        primary_hazard: isFire ? 'fire' : isPothole ? 'pothole' : isOverflow ? 'overflow' : null,
        pothole: {
          detected: isPothole,
          count: isPothole ? 2 : 0,
          confidence: isPothole ? 0.89 : 0.0,
          status: isPothole ? 'POTHOLE_DETECTED' : (isNormal ? 'STANDBY' : 'CLEAR'),
          bboxes: isPothole ? [[142, 310, 315, 440, 0.89]] : [],
        },
        fire_smoke: {
          detected: isFire,
          fire_detected: isFire,
          smoke_detected: false,
          confidence: isFire ? 0.94 : 0.0,
          status: isFire ? 'FIRE_ALERT' : (isNormal ? 'STANDBY' : 'CLEAR'),
          bboxes: isFire ? [[210, 150, 380, 340, 0.94, 'FIRE']] : [],
        },
        overflow: {
          detected: isOverflow,
          status: isOverflow ? 'OVERFLOW' : (isNormal ? 'STANDBY' : 'NORMAL'),
          confidence: isOverflow ? 0.88 : 0.12,
          label: isOverflow ? 'Overflowing waste bin with garbage spilling' : 'Normal clean waste bin',
        },
        esp32: {
          enabled: true,
          ip: '192.168.206.33',
          last_msg: isFire ? 'Sent /fire (200)' : isPothole ? 'Sent /pothole (200)' : isOverflow ? 'Sent /overflow (200)' : 'Sent /normal (200)',
          active_signal: isFire ? 'fire' : isPothole ? 'pothole' : isOverflow ? 'overflow' : 'normal',
        },
        total_incidents: isNormal ? 0 : 7,
      };

      setEngineState(simulatedState);
      toast.success(`Simulating ${type.toUpperCase()} detection event!`);
    }
  };

  // Helper flags: Exact binary presence (is the issue there or not!)
  const isPotholeIssue = Boolean(engineState.pothole?.detected || engineState.pothole?.count > 0);
  const isFireIssue = Boolean(engineState.fire_smoke?.fire_detected);
  const isSmokeIssue = Boolean(engineState.fire_smoke?.smoke_detected);
  const isFireSmokeIssue = Boolean(engineState.fire_smoke?.detected || isFireIssue || isSmokeIssue);
  const isOverflowIssue = Boolean(engineState.overflow?.detected || engineState.overflow?.status === 'OVERFLOW');

  const hasAnyActiveHazard = Boolean(
    engineState.primary_hazard || isPotholeIssue || isFireSmokeIssue || isOverflowIssue
  );

  return (
    <div className="space-y-6 pb-12">
      {/* 1. COMPACT LIVE CONTROLLER & STATUS DOCK */}
      <div className="glass-card-premium p-5 sm:p-6 border border-white/10 space-y-4">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <span className={`p-2.5 rounded-2xl border ${
              hasAnyActiveHazard
                ? 'bg-rose-500/20 text-rose-400 border-rose-500/40 animate-pulse'
                : engineState.running
                ? 'bg-cyan-500/15 text-cyan-400 border-cyan-500/30'
                : 'bg-white/5 text-[var(--text-dim)] border-white/10'
            }`}>
              <Activity size={20} className={engineState.running ? 'animate-pulse' : ''} />
            </span>
            <div>
              <div className="flex items-center gap-2.5">
                <h1 className="text-xl sm:text-2xl font-black text-[var(--text-main)] tracking-tight">
                  CivicSense Live Issue Monitor
                </h1>
                {engineState.running ? (
                  <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-black bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 animate-pulse">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                    SYSTEM LIVE
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-slate-500/10 text-slate-400 border border-slate-500/20">
                    STANDBY
                  </span>
                )}
              </div>
              <p className="text-xs text-[var(--text-muted)]">
                Autonomous real-time detection & ESP32 alert dispatch (<span className="font-mono text-cyan-300 font-bold">{engineState.esp32?.ip || '192.168.206.33'}</span>)
              </p>
            </div>
          </div>

          {/* Action Buttons & Simulation Menu */}
          <div className="flex flex-wrap items-center gap-2">
            {!engineState.running ? (
              <>
                <button
                  onClick={() => handleStartEngine('webcam')}
                  disabled={isLoadingAction}
                  className="glass-pill px-4 py-2 rounded-xl text-xs font-bold text-cyan-300 hover:text-white hover:bg-cyan-500/20 border-cyan-500/30 flex items-center gap-1.5 cursor-pointer disabled:opacity-50 transition-all shadow-sm"
                >
                  <PlayCircle size={15} className="text-cyan-400" />
                  <span>Start Camera</span>
                </button>
                <button
                  onClick={() => handleStartEngine('video')}
                  disabled={isLoadingAction}
                  className="glass-pill px-4 py-2 rounded-xl text-xs font-medium text-[var(--text-main)] hover:bg-white/10 border-white/15 flex items-center gap-1.5 cursor-pointer disabled:opacity-50 transition-all"
                >
                  <FileVideo size={15} className="text-cyan-400" />
                  <span>Sample Video</span>
                </button>
              </>
            ) : (
              <button
                onClick={handleStopEngine}
                disabled={isLoadingAction}
                className="glass-pill px-4 py-2 rounded-xl text-xs font-bold text-red-300 hover:text-white bg-red-500/20 hover:bg-red-500/30 border-red-500/40 flex items-center gap-1.5 cursor-pointer transition-all shadow-sm"
              >
                <Square size={13} className="fill-current" />
                <span>Stop Engine</span>
              </button>
            )}

            {/* Simulation Menu */}
            <div className="relative">
              <button
                onClick={() => setSimulateMenuOpen((prev) => !prev)}
                className="glass-pill px-3.5 py-2 rounded-xl text-xs font-semibold text-[var(--text-muted)] hover:text-white hover:bg-white/10 border-white/15 flex items-center gap-1.5 cursor-pointer transition-all"
              >
                <Zap size={14} className="text-amber-400" />
                <span>Test Alert</span>
                <ChevronDown size={13} className={`transition-transform duration-200 ${simulateMenuOpen ? 'rotate-180' : ''}`} />
              </button>

              {simulateMenuOpen && (
                <div className="absolute right-0 top-full mt-2 w-48 p-2 rounded-2xl glass-card-premium border border-white/20 shadow-2xl z-40 space-y-1 backdrop-blur-2xl">
                  <div className="text-[10px] font-black text-[var(--text-dim)] uppercase px-2 py-1">
                    Simulate Issue
                  </div>
                  <button
                    onClick={() => handleSimulate('pothole')}
                    className="w-full text-left px-2.5 py-1.5 rounded-xl text-xs font-medium text-amber-300 hover:bg-amber-500/20 flex items-center justify-between cursor-pointer"
                  >
                    <span>🕳️ Pothole</span>
                    <span className="text-[10px] opacity-60">Test</span>
                  </button>
                  <button
                    onClick={() => handleSimulate('fire')}
                    className="w-full text-left px-2.5 py-1.5 rounded-xl text-xs font-medium text-rose-300 hover:bg-rose-500/20 flex items-center justify-between cursor-pointer"
                  >
                    <span>🔥 Fire Hazard</span>
                    <span className="text-[10px] opacity-60">Test</span>
                  </button>
                  <button
                    onClick={() => handleSimulate('overflow')}
                    className="w-full text-left px-2.5 py-1.5 rounded-xl text-xs font-medium text-purple-300 hover:bg-purple-500/20 flex items-center justify-between cursor-pointer"
                  >
                    <span>🗑️ Waste Overflow</span>
                    <span className="text-[10px] opacity-60">Test</span>
                  </button>
                  <button
                    onClick={() => handleSimulate('all')}
                    className="w-full text-left px-2.5 py-1.5 rounded-xl text-xs font-medium text-cyan-300 hover:bg-cyan-500/20 flex items-center justify-between cursor-pointer"
                  >
                    <span>⚡ All Issues</span>
                    <span className="text-[10px] opacity-60">All</span>
                  </button>
                  <div className="border-t border-white/10 my-1" />
                  <button
                    onClick={() => handleSimulate('normal')}
                    className="w-full text-left px-2.5 py-1.5 rounded-xl text-xs font-medium text-emerald-300 hover:bg-emerald-500/20 flex items-center justify-between cursor-pointer"
                  >
                    <span>✓ Clear (Normal)</span>
                    <span className="text-[10px] opacity-60">Reset</span>
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Live Stream Telemetry Ribbon */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-2 border-t border-white/10 text-xs">
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-white/[0.03]">
            <span className="text-[var(--text-dim)] font-medium">Source:</span>
            <span className="font-bold text-[var(--text-main)] truncate">
              {engineState.source === '0' ? 'Camera 0' : engineState.source ? engineState.source.split(/[\\/]/).pop() : 'Camera 0'}
            </span>
          </div>
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-white/[0.03]">
            <span className="text-[var(--text-dim)] font-medium">Speed:</span>
            <span className="font-bold text-cyan-400 font-mono">
              {engineState.fps > 0 ? `${engineState.fps.toFixed(1)} FPS` : engineState.running ? 'Active' : '0 FPS'}
            </span>
          </div>
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-white/[0.03]">
            <span className="text-[var(--text-dim)] font-medium">ESP32 Signal:</span>
            <span className={`font-bold truncate ${hasAnyActiveHazard ? 'text-rose-400 animate-pulse' : 'text-emerald-400'}`}>
              {engineState.esp32?.last_msg || 'Sent /normal (200)'}
            </span>
          </div>
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-white/[0.03]">
            <span className="text-[var(--text-dim)] font-medium">Frames:</span>
            <span className="font-bold text-[var(--text-main)] font-mono">
              #{engineState.frame_idx || 0}
            </span>
          </div>
        </div>
      </div>

      {/* 2. THE 3 ISSUE STATUS CARDS (PURE BINARY: ISSUE DETECTED vs CLEAR) */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">

        {/* ========================================================================= */}
        {/* CARD 1: POTHOLE                                                           */}
        {/* ========================================================================= */}
        <div
          className={`glass-card-premium p-6 rounded-3xl flex flex-col justify-between transition-all duration-300 relative overflow-hidden ${
            isPotholeIssue
              ? 'border-amber-500/70 bg-gradient-to-b from-amber-500/15 via-[var(--bg-surface)] to-[var(--bg-surface)] shadow-[0_0_35px_rgba(245,158,11,0.3)]'
              : 'hover:border-white/20'
          }`}
        >
          <div>
            <div className="flex items-center justify-between mb-5">
              <div className="flex items-center gap-3">
                <div
                  className={`w-12 h-12 rounded-2xl flex items-center justify-center transition-all ${
                    isPotholeIssue
                      ? 'bg-amber-500 text-black shadow-lg shadow-amber-500/50 animate-bounce'
                      : 'glass-pill text-amber-400'
                  }`}
                >
                  <Layers size={24} />
                </div>
                <div>
                  <h2 className="text-lg font-black text-[var(--text-main)] tracking-tight">
                    Pothole Issue
                  </h2>
                  <span className="text-[11px] font-bold text-[var(--text-dim)] uppercase tracking-wider">
                    Road Surface Scanner
                  </span>
                </div>
              </div>

              {isPotholeIssue ? (
                <span className="px-3 py-1 rounded-full text-xs font-black bg-amber-500 text-black shadow-md animate-pulse">
                  ISSUE DETECTED
                </span>
              ) : engineState.running ? (
                <span className="px-3 py-1 rounded-full text-xs font-bold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 flex items-center gap-1">
                  <CheckCircle2 size={13} />
                  CLEAR
                </span>
              ) : (
                <span className="px-3 py-1 rounded-full text-xs font-medium text-[var(--text-dim)] bg-white/5 border border-white/5">
                  STANDBY
                </span>
              )}
            </div>

            {/* Central Binary Status Hero Block */}
            <div className={`p-6 rounded-2xl my-3 flex flex-col items-center justify-center text-center transition-all ${
              isPotholeIssue
                ? 'bg-amber-500/20 border-2 border-amber-500/60 shadow-inner'
                : 'bg-white/[0.02] border border-white/5'
            }`}>
              {isPotholeIssue ? (
                <div className="space-y-1">
                  <AlertTriangle size={36} className="text-amber-400 mx-auto animate-pulse mb-2" />
                  <div className="text-2xl font-black text-amber-300 tracking-wide uppercase">
                    POTHOLE DETECTED
                  </div>
                  <p className="text-xs text-amber-200/90 font-medium">
                    Road damage identified in camera view
                  </p>
                </div>
              ) : (
                <div className="space-y-1">
                  <CheckCircle2 size={36} className="text-emerald-400 mx-auto mb-2" />
                  <div className="text-2xl font-black text-emerald-300 tracking-wide uppercase">
                    NO POTHOLE
                  </div>
                  <p className="text-xs text-[var(--text-muted)]">
                    Road surface in normal condition
                  </p>
                </div>
              )}
            </div>
          </div>

          {/* Bottom Alert Signal */}
          <div className="mt-4 pt-3 border-t border-white/10 flex items-center justify-between text-xs">
            <span className="text-[var(--text-dim)] font-medium">ESP32 Action:</span>
            <span className={`font-mono font-bold ${isPotholeIssue ? 'text-amber-300' : 'text-emerald-400'}`}>
              {isPotholeIssue ? 'NOTIFYING /pothole' : '/normal (clear)'}
            </span>
          </div>
        </div>

        {/* ========================================================================= */}
        {/* CARD 2: FIRE & SMOKE                                                      */}
        {/* ========================================================================= */}
        <div
          className={`glass-card-premium p-6 rounded-3xl flex flex-col justify-between transition-all duration-300 relative overflow-hidden ${
            isFireSmokeIssue
              ? 'border-rose-500/70 bg-gradient-to-b from-rose-500/20 via-[var(--bg-surface)] to-[var(--bg-surface)] shadow-[0_0_35px_rgba(244,63,94,0.35)]'
              : 'hover:border-white/20'
          }`}
        >
          <div>
            <div className="flex items-center justify-between mb-5">
              <div className="flex items-center gap-3">
                <div
                  className={`w-12 h-12 rounded-2xl flex items-center justify-center transition-all ${
                    isFireSmokeIssue
                      ? 'bg-rose-500 text-white shadow-lg shadow-rose-500/50 animate-bounce'
                      : 'glass-pill text-rose-400'
                  }`}
                >
                  <Flame size={24} />
                </div>
                <div>
                  <h2 className="text-lg font-black text-[var(--text-main)] tracking-tight">
                    Fire & Smoke Issue
                  </h2>
                  <span className="text-[11px] font-bold text-[var(--text-dim)] uppercase tracking-wider">
                    Hazard Safety Scanner
                  </span>
                </div>
              </div>

              {isFireSmokeIssue ? (
                <span className="px-3 py-1 rounded-full text-xs font-black bg-rose-600 text-white shadow-md animate-pulse">
                  {isFireIssue ? 'FIRE OUTBREAK' : 'SMOKE DETECTED'}
                </span>
              ) : engineState.running ? (
                <span className="px-3 py-1 rounded-full text-xs font-bold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 flex items-center gap-1">
                  <CheckCircle2 size={13} />
                  CLEAR
                </span>
              ) : (
                <span className="px-3 py-1 rounded-full text-xs font-medium text-[var(--text-dim)] bg-white/5 border border-white/5">
                  STANDBY
                </span>
              )}
            </div>

            {/* Central Binary Status Hero Block */}
            <div className={`p-6 rounded-2xl my-3 flex flex-col items-center justify-center text-center transition-all ${
              isFireSmokeIssue
                ? 'bg-rose-500/25 border-2 border-rose-500/70 shadow-inner'
                : 'bg-white/[0.02] border border-white/5'
            }`}>
              {isFireSmokeIssue ? (
                <div className="space-y-1">
                  <Flame size={36} className="text-rose-400 mx-auto animate-pulse mb-2" />
                  <div className="text-2xl font-black text-rose-300 tracking-wide uppercase">
                    {isFireIssue ? 'FIRE DETECTED!' : 'SMOKE DETECTED!'}
                  </div>
                  <p className="text-xs text-rose-200/90 font-medium">
                    Critical thermal emergency hazard active
                  </p>
                </div>
              ) : (
                <div className="space-y-1">
                  <CheckCircle2 size={36} className="text-emerald-400 mx-auto mb-2" />
                  <div className="text-2xl font-black text-emerald-300 tracking-wide uppercase">
                    NO FIRE / SMOKE
                  </div>
                  <p className="text-xs text-[var(--text-muted)]">
                    Zero thermal activity or fire detected
                  </p>
                </div>
              )}
            </div>
          </div>

          {/* Bottom Alert Signal */}
          <div className="mt-4 pt-3 border-t border-white/10 flex items-center justify-between text-xs">
            <span className="text-[var(--text-dim)] font-medium">ESP32 Action:</span>
            <span className={`font-mono font-bold ${isFireSmokeIssue ? 'text-rose-400' : 'text-emerald-400'}`}>
              {isFireIssue ? 'TRIGGERING /fire' : isSmokeIssue ? 'TRIGGERING /smoke' : '/normal (clear)'}
            </span>
          </div>
        </div>

        {/* ========================================================================= */}
        {/* CARD 3: WASTE OVERFLOW                                                    */}
        {/* ========================================================================= */}
        <div
          className={`glass-card-premium p-6 rounded-3xl flex flex-col justify-between transition-all duration-300 relative overflow-hidden ${
            isOverflowIssue
              ? 'border-purple-500/70 bg-gradient-to-b from-purple-500/20 via-[var(--bg-surface)] to-[var(--bg-surface)] shadow-[0_0_35px_rgba(168,85,247,0.35)]'
              : 'hover:border-white/20'
          }`}
        >
          <div>
            <div className="flex items-center justify-between mb-5">
              <div className="flex items-center gap-3">
                <div
                  className={`w-12 h-12 rounded-2xl flex items-center justify-center transition-all ${
                    isOverflowIssue
                      ? 'bg-purple-600 text-white shadow-lg shadow-purple-500/50 animate-bounce'
                      : 'glass-pill text-purple-400'
                  }`}
                >
                  <Trash2 size={24} />
                </div>
                <div>
                  <h2 className="text-lg font-black text-[var(--text-main)] tracking-tight">
                    Waste Overflow Issue
                  </h2>
                  <span className="text-[11px] font-bold text-[var(--text-dim)] uppercase tracking-wider">
                    Sanitation Scanner
                  </span>
                </div>
              </div>

              {isOverflowIssue ? (
                <span className="px-3 py-1 rounded-full text-xs font-black bg-purple-600 text-white shadow-md animate-pulse">
                  OVERFLOW DETECTED
                </span>
              ) : engineState.running ? (
                <span className="px-3 py-1 rounded-full text-xs font-bold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 flex items-center gap-1">
                  <CheckCircle2 size={13} />
                  NORMAL
                </span>
              ) : (
                <span className="px-3 py-1 rounded-full text-xs font-medium text-[var(--text-dim)] bg-white/5 border border-white/5">
                  STANDBY
                </span>
              )}
            </div>

            {/* Central Binary Status Hero Block */}
            <div className={`p-6 rounded-2xl my-3 flex flex-col items-center justify-center text-center transition-all ${
              isOverflowIssue
                ? 'bg-purple-500/25 border-2 border-purple-500/70 shadow-inner'
                : 'bg-white/[0.02] border border-white/5'
            }`}>
              {isOverflowIssue ? (
                <div className="space-y-1">
                  <Trash2 size={36} className="text-purple-400 mx-auto animate-pulse mb-2" />
                  <div className="text-2xl font-black text-purple-300 tracking-wide uppercase">
                    GARBAGE OVERFLOW!
                  </div>
                  <p className="text-xs text-purple-200/90 font-medium">
                    Waste bin overflowing with litter spilling
                  </p>
                </div>
              ) : (
                <div className="space-y-1">
                  <CheckCircle2 size={36} className="text-emerald-400 mx-auto mb-2" />
                  <div className="text-2xl font-black text-emerald-300 tracking-wide uppercase">
                    BIN NORMAL
                  </div>
                  <p className="text-xs text-[var(--text-muted)]">
                    No garbage overflow detected
                  </p>
                </div>
              )}
            </div>
          </div>

          {/* Bottom Alert Signal */}
          <div className="mt-4 pt-3 border-t border-white/10 flex items-center justify-between text-xs">
            <span className="text-[var(--text-dim)] font-medium">ESP32 Action:</span>
            <span className={`font-mono font-bold ${isOverflowIssue ? 'text-purple-300' : 'text-emerald-400'}`}>
              {isOverflowIssue ? 'TRIGGERING /overflow' : '/normal (clear)'}
            </span>
          </div>
        </div>
      </div>

      {/* 3. DEDICATED REAL-TIME ALERT SYSTEM & HARDWARE DISPATCH CENTER */}
      <div className="glass-card-premium p-6 border border-white/10 rounded-3xl space-y-5">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-white/10 pb-4">
          <div className="flex items-center gap-3">
            <div
              className={`p-2.5 rounded-2xl flex items-center justify-center transition-all ${
                hasAnyActiveHazard
                  ? 'bg-rose-500/20 text-rose-300 border border-rose-500/40 animate-pulse'
                  : engineState.running
                  ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                  : 'bg-white/5 text-[var(--text-dim)] border border-white/10'
              }`}
            >
              {hasAnyActiveHazard ? <ShieldAlert size={24} /> : <ShieldCheck size={24} />}
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-lg font-black text-[var(--text-main)] tracking-tight">
                  Emergency Alert & Hardware Dispatch Center
                </h2>
                <span
                  className={`px-2.5 py-0.5 rounded-full text-[10px] font-black uppercase tracking-wider ${
                    hasAnyActiveHazard
                      ? 'bg-rose-500/25 text-rose-300 border border-rose-500/40 animate-pulse'
                      : engineState.running
                      ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30'
                      : 'bg-slate-500/10 text-slate-400 border border-slate-500/20'
                  }`}
                >
                  {hasAnyActiveHazard ? '🚨 ISSUE ACTIVE' : engineState.running ? '🟢 ARMED & LISTENING' : '⚪ STANDBY'}
                </span>
              </div>
              <p className="text-xs text-[var(--text-muted)]">
                ESP32 hardware module: <span className="font-mono text-cyan-300 font-bold">{engineState.esp32?.ip || '192.168.206.33'}</span>
              </p>
            </div>
          </div>

          {/* Quick Sound Toggle + Direct Simulators */}
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => {
                const next = !soundEnabled;
                setSoundEnabled(next);
                toast.info(next ? 'Browser audio alarm chime enabled' : 'Browser audio alarm chime muted');
                if (next) triggerAudioChime('pothole');
              }}
              className={`glass-pill px-3 py-1.5 rounded-xl text-xs font-semibold flex items-center gap-1.5 transition-all cursor-pointer ${
                soundEnabled ? 'text-amber-300 bg-amber-500/20 border-amber-500/40' : 'text-[var(--text-muted)] hover:bg-white/10'
              }`}
              title="Toggle Web Audio siren"
            >
              {soundEnabled ? <Volume2 size={15} className="text-amber-400 animate-bounce" /> : <VolumeX size={15} />}
              <span>{soundEnabled ? 'Alarm Sound ON' : 'Alarm Sound Muted'}</span>
            </button>

            <div className="flex items-center gap-1.5 bg-white/[0.04] p-1 rounded-2xl border border-white/10">
              <span className="text-[10px] font-bold text-[var(--text-dim)] uppercase px-2">Trigger Test:</span>
              <button
                onClick={() => handleSimulate('pothole')}
                className="px-2.5 py-1 rounded-xl text-[11px] font-bold text-amber-300 bg-amber-500/15 hover:bg-amber-500/30 border border-amber-500/30 cursor-pointer transition-all"
              >
                Pothole
              </button>
              <button
                onClick={() => handleSimulate('fire')}
                className="px-2.5 py-1 rounded-xl text-[11px] font-bold text-rose-300 bg-rose-500/15 hover:bg-rose-500/30 border border-rose-500/30 cursor-pointer transition-all"
              >
                Fire
              </button>
              <button
                onClick={() => handleSimulate('overflow')}
                className="px-2.5 py-1 rounded-xl text-[11px] font-bold text-purple-300 bg-purple-500/15 hover:bg-purple-500/30 border border-purple-500/30 cursor-pointer transition-all"
              >
                Overflow
              </button>
              <button
                onClick={() => handleSimulate('normal')}
                className="px-2.5 py-1 rounded-xl text-[11px] font-bold text-emerald-300 bg-emerald-500/15 hover:bg-emerald-500/30 border border-emerald-500/30 cursor-pointer transition-all"
              >
                Clear
              </button>
            </div>
          </div>
        </div>

        {/* High-Visibility Alert Banner */}
        {hasAnyActiveHazard ? (
          <div className="p-5 rounded-2xl border-2 border-rose-500/70 bg-gradient-to-r from-rose-500/30 via-amber-500/20 to-purple-500/25 shadow-[0_0_40px_rgba(244,63,94,0.4)] flex flex-col sm:flex-row items-center justify-between gap-4 animate-pulse">
            <div className="flex items-center gap-4">
              <div className="w-12 h-12 rounded-2xl bg-rose-600 text-white flex items-center justify-center shadow-lg shadow-rose-600/60 shrink-0">
                <AlertTriangle size={26} className="animate-bounce" />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-xs font-black text-rose-200 uppercase tracking-widest">
                    ACTIVE HAZARD DETECTED
                  </span>
                  <span className="text-[11px] font-extrabold text-white bg-rose-500/60 px-2 py-0.5 rounded-full border border-rose-400">
                    DISPATCH TRANSMITTED
                  </span>
                </div>
                <h3 className="text-base sm:text-lg font-black text-white mt-0.5">
                  {engineState.primary_hazard === 'fire' || isFireIssue
                    ? '🔥 Open Flame / Fire Outbreak Detected in Frame!'
                    : engineState.primary_hazard === 'smoke' || isSmokeIssue
                    ? '💨 Heavy Smoke Cloud Identified in Frame!'
                    : engineState.primary_hazard === 'pothole' || isPotholeIssue
                    ? '🕳️ Dangerous Road Surface Pothole Detected!'
                    : '🗑️ Waste Bin Garbage Overflow Detected!'}
                </h3>
                <p className="text-xs text-rose-200/95 font-mono mt-0.5">
                  Alert sent: <span className="font-bold underline">/{engineState.primary_hazard || (isFireIssue ? 'fire' : isPotholeIssue ? 'pothole' : 'overflow')}</span> to http://{engineState.esp32?.ip || '192.168.206.33'} ({engineState.esp32?.last_msg || 'Sent /alert'})
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2 shrink-0">
              <span className="px-4 py-2 rounded-full text-xs font-black bg-rose-600 text-white shadow-lg animate-ping">
                BUZZER FIRING
              </span>
              <span className="px-4 py-2 rounded-full text-xs font-black bg-rose-500/40 text-rose-100 border border-rose-400">
                LED ACTIVE
              </span>
            </div>
          </div>
        ) : (
          <div className="p-4 rounded-2xl bg-emerald-500/[0.08] border border-emerald-500/25 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-3 h-3 rounded-full bg-emerald-400 animate-pulse shrink-0" />
              <div>
                <span className="text-sm font-black text-emerald-300 uppercase tracking-wider">
                  All Systems Clear — No Issues Detected
                </span>
                <p className="text-xs text-[var(--text-muted)]">
                  Monitoring live stream without interruptions. ESP32 signal: <span className="font-mono text-emerald-400 font-bold">{engineState.esp32?.last_msg || 'Sent /normal'}</span>
                </p>
              </div>
            </div>
            <span className="px-3 py-1 rounded-full text-xs font-bold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 shrink-0">
              NORMAL
            </span>
          </div>
        )}

        {/* Live Issue Summary Row (Is the issue there or not?) */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-1">
          <div className={`p-4 rounded-2xl border transition-all ${
            isPotholeIssue
              ? 'bg-amber-500/15 border-amber-500/40 text-amber-200'
              : 'bg-white/[0.02] border-white/5 text-[var(--text-muted)]'
          }`}>
            <span className="text-[10px] font-bold uppercase tracking-wider text-[var(--text-dim)] block mb-1">
              Pothole Status
            </span>
            <div className="flex items-center justify-between">
              <span className={`text-sm font-black ${isPotholeIssue ? 'text-amber-300' : 'text-emerald-400'}`}>
                {isPotholeIssue ? '⚠️ ISSUE FOUND' : '✓ CLEAR'}
              </span>
              <span className="text-[11px] font-mono">
                {isPotholeIssue ? 'ALERT' : 'OK'}
              </span>
            </div>
          </div>

          <div className={`p-4 rounded-2xl border transition-all ${
            isFireSmokeIssue
              ? 'bg-rose-500/15 border-rose-500/40 text-rose-200'
              : 'bg-white/[0.02] border-white/5 text-[var(--text-muted)]'
          }`}>
            <span className="text-[10px] font-bold uppercase tracking-wider text-[var(--text-dim)] block mb-1">
              Fire & Smoke Status
            </span>
            <div className="flex items-center justify-between">
              <span className={`text-sm font-black ${isFireSmokeIssue ? 'text-rose-400' : 'text-emerald-400'}`}>
                {isFireIssue ? '🔥 FIRE FOUND' : isSmokeIssue ? '💨 SMOKE FOUND' : '✓ CLEAR'}
              </span>
              <span className="text-[11px] font-mono">
                {isFireSmokeIssue ? 'ALERT' : 'OK'}
              </span>
            </div>
          </div>

          <div className={`p-4 rounded-2xl border transition-all ${
            isOverflowIssue
              ? 'bg-purple-500/15 border-purple-500/40 text-purple-200'
              : 'bg-white/[0.02] border-white/5 text-[var(--text-muted)]'
          }`}>
            <span className="text-[10px] font-bold uppercase tracking-wider text-[var(--text-dim)] block mb-1">
              Waste Bin Status
            </span>
            <div className="flex items-center justify-between">
              <span className={`text-sm font-black ${isOverflowIssue ? 'text-purple-300' : 'text-emerald-400'}`}>
                {isOverflowIssue ? '🗑️ OVERFLOW FOUND' : '✓ NORMAL'}
              </span>
              <span className="text-[11px] font-mono">
                {isOverflowIssue ? 'ALERT' : 'OK'}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
