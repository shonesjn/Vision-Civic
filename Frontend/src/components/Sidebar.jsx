import React, { useState } from 'react';
import { NavLink } from 'react-router-dom';
import {
  Home,
  X,
  PanelLeftClose,
  PanelLeftOpen,
} from 'lucide-react';
import VisionCivicLogo from './VisionCivicLogo';
import ThemeToggle from './ThemeToggle';
import { SimpleTooltip } from './ui/tooltip';

export default function Sidebar({ isOpen, onClose }) {
  const [isCollapsed, setIsCollapsed] = useState(() => {
    try {
      return localStorage.getItem('civic_sidebar_collapsed') === 'true';
    } catch {
      return false;
    }
  });

  const toggleCollapse = () => {
    setIsCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem('civic_sidebar_collapsed', String(next));
      } catch (e) {
        console.error(e);
      }
      return next;
    });
  };

  const navItems = [
    { to: '/', label: 'Home', icon: Home },
  ];

  return (
    <>
      {/* Mobile Backdrop */}
      {isOpen && (
        <div
          onClick={onClose}
          className="fixed inset-0 bg-black/60 backdrop-blur-sm z-40 lg:hidden"
        />
      )}

      <aside
        className={`bg-[var(--bg-secondary)] border-r border-[var(--border-subtle)] flex flex-col h-screen fixed lg:sticky top-0 z-50 transition-all duration-300 ease-in-out ${
          isOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'
        } ${isCollapsed ? 'lg:w-20' : 'lg:w-64'} w-64`}
      >
        {/* Brand Header */}
        <div className={`p-4 border-b border-[var(--border-subtle)] flex items-center ${isCollapsed ? 'justify-center flex-col gap-2' : 'justify-between'}`}>
          <div className="flex items-center gap-2.5 overflow-hidden">
            <VisionCivicLogo size={34} showText={!isCollapsed} />
          </div>

          <div className="flex items-center gap-1">
            {/* Desktop Collapse / Expand Button */}
            <button
              onClick={toggleCollapse}
              className="hidden lg:flex p-1.5 rounded-lg text-[var(--text-muted)] hover:text-[var(--text-main)] hover:bg-[var(--bg-surface)] transition-colors cursor-pointer"
              title={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
              aria-label={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            >
              {isCollapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
            </button>

            {/* Mobile Close Button */}
            <button
              onClick={onClose}
              className="lg:hidden text-[var(--text-muted)] hover:text-[var(--text-main)] p-1.5 rounded-lg hover:bg-[var(--bg-surface)] transition-colors cursor-pointer"
              aria-label="Close Navigation"
            >
              <X size={20} />
            </button>
          </div>
        </div>

        {/* Navigation Links */}
        <nav className="flex-1 p-3 flex flex-col gap-1.5 overflow-y-auto overflow-x-hidden">
          {navItems.map((item) => {
            const Icon = item.icon;

            const linkContent = (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === '/'}
                onClick={onClose}
                className={({ isActive }) =>
                  `flex items-center rounded-xl text-sm font-medium transition-all duration-200 relative group ${
                    isCollapsed
                      ? 'justify-center w-12 h-12 mx-auto'
                      : 'gap-3.5 px-3.5 py-3'
                  } ${
                    isActive
                      ? 'bg-[var(--bg-surface)] text-[var(--primary)] font-semibold border-l-4 border-[var(--primary)] shadow-sm'
                      : 'text-[var(--text-muted)] hover:bg-[var(--bg-surface)] hover:text-[var(--text-main)]'
                  }`
                }
              >
                <div className="relative shrink-0 flex items-center justify-center">
                  <Icon size={20} />
                  {item.badge && (
                    <span className="absolute -top-1 -right-1 w-2.5 h-2.5 rounded-full bg-red-500 animate-pulse" />
                  )}
                </div>

                {!isCollapsed && (
                  <>
                    <span className="flex-1 truncate">{item.label}</span>
                    {item.badge && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-500/20 text-red-400 font-bold shrink-0">
                        {item.badge}
                      </span>
                    )}
                  </>
                )}
              </NavLink>
            );

            if (isCollapsed) {
              return (
                <SimpleTooltip key={item.to} content={item.label} side="right">
                  <div>{linkContent}</div>
                </SimpleTooltip>
              );
            }

            return linkContent;
          })}
        </nav>

        {/* Footer Area: Theme Toggle & System Status */}
        <div className="p-3 border-t border-[var(--border-subtle)] bg-[var(--bg-surface)]/40 flex flex-col gap-2.5">
          {/* Theme Toggle in Sidebar */}
          {isCollapsed ? (
            <div className="flex justify-center">
              <ThemeToggle direction="right" />
            </div>
          ) : (
            <div className="flex items-center justify-between px-2.5 py-1.5 rounded-lg bg-[var(--bg-secondary)] border border-[var(--border-subtle)]">
              <span className="text-xs font-medium text-[var(--text-dim)]">
                Appearance
              </span>
              <ThemeToggle direction="up" align="right" />
            </div>
          )}

          {/* System Status Pill */}
          {!isCollapsed ? (
            <div className="flex items-center gap-2 px-2.5 py-2 rounded-lg bg-[var(--bg-secondary)]/70 border border-[var(--border-subtle)] text-[11px] text-[var(--text-muted)]">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
              </span>
              <span className="truncate font-medium text-[var(--text-dim)]">
                AI Engine • Ready
              </span>
            </div>
          ) : (
            <SimpleTooltip content="AI Engine: Ready" side="right">
              <div className="flex justify-center py-1">
                <span className="relative flex h-2.5 w-2.5">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                  <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-emerald-500"></span>
                </span>
              </div>
            </SimpleTooltip>
          )}
        </div>
      </aside>
    </>
  );
}

