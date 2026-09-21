"use client";

import { useState } from "react";

import { addBoardAction, deleteBoardAction, toggleBoardAction, type ActionResult } from "@/app/actions";
import { dateTime } from "@/lib/format";
import type { BoardInfo, PlatformInfo } from "@/lib/types";

import { Toast } from "./Toast";

const ATS_KINDS = ["greenhouse", "lever", "ashby", "workable", "smartrecruiters"];

/**
 * Which platforms the Scout polls, and which company boards are live on them.
 *
 * The platform checkboxes are the coarse control and the board list the fine
 * one: selecting `greenhouse` polls every seeded Greenhouse board, and the
 * per-board switch takes one company out without giving up the platform.
 */
export function PlatformPicker({
  platforms,
  boards: initialBoards,
  selected,
  onToggle,
}: {
  platforms: PlatformInfo[];
  boards: BoardInfo[];
  selected: string[];
  onToggle: (id: string) => void;
}) {
  const [boards, setBoards] = useState(initialBoards);
  const [busy, setBusy] = useState<string | null>(null);
  const [toast, setToast] = useState<ActionResult | null>(null);
  const [newBoard, setNewBoard] = useState({ kind: "greenhouse", slug: "", company_name: "" });

  const toggleBoard = (board: BoardInfo) => {
    setBusy(board.id);
    const next = !board.enabled;
    void toggleBoardAction(board.id, next).then((result) => {
      setBusy(null);
      setToast(result);
      if (result.ok) {
        setBoards((rows) => rows.map((row) => (row.id === board.id ? { ...row, enabled: next } : row)));
      }
    });
  };

  const removeBoard = (board: BoardInfo) => {
    setBusy(board.id);
    void deleteBoardAction(board.id, `${board.kind}/${board.slug}`).then((result) => {
      setBusy(null);
      setToast(result);
      if (result.ok) setBoards((rows) => rows.filter((row) => row.id !== board.id));
    });
  };

  const add = () => {
    if (!newBoard.slug.trim()) {
      setToast({ ok: false, message: "A board needs the company's slug on that platform" });
      return;
    }
    setBusy("new");
    void addBoardAction({
      kind: newBoard.kind,
      slug: newBoard.slug.trim(),
      company_name: newBoard.company_name.trim() || undefined,
    }).then((result) => {
      setBusy(null);
      setToast(result);
      if (result.ok) setNewBoard({ kind: newBoard.kind, slug: "", company_name: "" });
    });
  };

  const dead = boards.filter((board) => board.last_error);

  return (
    <section className="rounded-xl border border-edge bg-panel/60 shadow-panel">
      <header className="border-b border-edge/60 px-4 py-3">
        <h2 className="text-sm font-medium text-fg">Platforms</h2>
        <p className="mt-0.5 text-2xs text-faint">
          Leave every box unticked to poll all of them. Nothing here is fetched by a
          browser: LinkedIn and Indeed are harvested by the extension as you browse.
        </p>
      </header>

      <div className="grid gap-2 px-4 py-4 sm:grid-cols-2 lg:grid-cols-3">
        {platforms.map((platform) => {
          const on = selected.includes(platform.id);
          return (
            <label
              key={platform.id}
              className={`flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-xs transition-colors duration-150 ${
                on ? "border-accent/40 bg-accent/10 text-fg" : "border-edge bg-raised text-muted hover:border-edge-strong"
              }`}
            >
              <input
                type="checkbox"
                checked={on}
                onChange={() => onToggle(platform.id)}
                className="h-3.5 w-3.5 rounded border-edge bg-ink accent-accent"
              />
              <span>{platform.label}</span>
              <span className="ml-auto text-2xs text-faint">
                {platform.kind === "ats" ? "boards" : "aggregator"}
              </span>
            </label>
          );
        })}
      </div>

      <div className="border-t border-edge/60">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5">
          <h3 className="text-2xs uppercase tracking-[0.14em] text-faint">Company boards</h3>
          <span className="text-2xs text-faint">
            {boards.length} on file · {boards.filter((b) => b.enabled).length} enabled
          </span>
          {dead.length > 0 && (
            <span className="text-2xs text-marginal">
              {dead.length} returning errors — check the slug or drop the board
            </span>
          )}
        </div>

        <div className="max-h-80 overflow-auto px-4 pb-3">
          <table className="w-full">
            <thead>
              <tr>
                <th className="px-2 py-1.5 text-left text-2xs font-medium uppercase tracking-[0.12em] text-faint">
                  Board
                </th>
                <th className="px-2 py-1.5 text-left text-2xs font-medium uppercase tracking-[0.12em] text-faint">
                  Found
                </th>
                <th className="px-2 py-1.5 text-left text-2xs font-medium uppercase tracking-[0.12em] text-faint">
                  Last polled
                </th>
                <th className="px-2 py-1.5" />
              </tr>
            </thead>
            <tbody>
              {boards.map((board) => (
                <tr key={board.id} className="border-t border-edge/40">
                  <td className="px-2 py-1.5">
                    <span className="font-mono text-xs text-fg/90">
                      {board.kind}/{board.slug}
                    </span>
                    {board.company_name && (
                      <span className="ml-2 text-2xs text-faint">{board.company_name}</span>
                    )}
                    {board.last_error && (
                      <span className="ml-2 text-2xs text-marginal" title={board.last_error}>
                        {board.last_error.slice(0, 40)}
                      </span>
                    )}
                  </td>
                  <td className="px-2 py-1.5 font-mono text-xs tabular-nums text-faint">
                    {board.jobs_found ?? "—"}
                  </td>
                  <td className="px-2 py-1.5 font-mono text-2xs tabular-nums text-faint">
                    {board.last_polled_at ? dateTime(board.last_polled_at) : "never"}
                  </td>
                  <td className="px-2 py-1.5 text-right">
                    <button
                      type="button"
                      onClick={() => toggleBoard(board)}
                      disabled={busy !== null}
                      className="rounded border border-edge px-2 py-0.5 text-2xs text-muted
                                 transition-colors duration-150 hover:border-edge-strong hover:text-fg
                                 disabled:opacity-50"
                    >
                      {board.enabled ? "disable" : "enable"}
                    </button>
                    <button
                      type="button"
                      onClick={() => removeBoard(board)}
                      disabled={busy !== null}
                      aria-label={`Remove ${board.kind}/${board.slug}`}
                      className="ml-1 rounded border border-edge px-2 py-0.5 text-2xs text-faint
                                 transition-colors duration-150 hover:border-marginal/40 hover:text-marginal
                                 disabled:opacity-50"
                    >
                      ×
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="flex flex-wrap items-end gap-2 border-t border-edge/60 px-4 py-3">
          <label className="text-2xs uppercase tracking-[0.12em] text-faint">
            <span className="mb-1 block">Platform</span>
            <select
              value={newBoard.kind}
              onChange={(event) => setNewBoard((b) => ({ ...b, kind: event.target.value }))}
              className="rounded-lg border border-edge bg-ink/60 px-2 py-1.5 text-xs text-fg focus:border-accent/50 focus:outline-none"
            >
              {ATS_KINDS.map((kind) => (
                <option key={kind} value={kind}>
                  {kind}
                </option>
              ))}
            </select>
          </label>
          <label className="text-2xs uppercase tracking-[0.12em] text-faint">
            <span className="mb-1 block">Slug</span>
            <input
              value={newBoard.slug}
              onChange={(event) => setNewBoard((b) => ({ ...b, slug: event.target.value }))}
              placeholder="stripe"
              className="w-32 rounded-lg border border-edge bg-ink/60 px-2 py-1.5 font-mono text-xs text-fg focus:border-accent/50 focus:outline-none"
            />
          </label>
          <label className="text-2xs uppercase tracking-[0.12em] text-faint">
            <span className="mb-1 block">Company</span>
            <input
              value={newBoard.company_name}
              onChange={(event) => setNewBoard((b) => ({ ...b, company_name: event.target.value }))}
              placeholder="Stripe"
              className="w-36 rounded-lg border border-edge bg-ink/60 px-2 py-1.5 text-xs text-fg focus:border-accent/50 focus:outline-none"
            />
          </label>
          <button
            type="button"
            onClick={add}
            disabled={busy !== null}
            className="rounded-lg border border-edge bg-raised px-3 py-1.5 text-xs text-muted
                       transition-colors duration-150 hover:border-edge-strong hover:text-fg
                       disabled:opacity-50"
          >
            Add board
          </button>
        </div>
      </div>

      <Toast toast={toast} onDismiss={() => setToast(null)} />
    </section>
  );
}
